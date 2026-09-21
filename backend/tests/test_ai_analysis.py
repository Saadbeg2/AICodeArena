import json
import unittest
from typing import Optional
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai_analysis import (
    AI_ANALYSIS_DISABLED_MESSAGE,
    AI_ANALYSIS_PROMPT_VERSION,
    AI_ANALYSIS_WRONG_ANSWER_PROMPT_VERSION,
    _build_wrong_answer_reviewer_system_prompt,
    _build_reviewer_system_prompt,
    _build_reviewer_user_prompt,
    build_ai_analysis_input,
    determine_ai_analysis_review_mode,
    generate_ai_analysis,
    generate_mock_ai_analysis,
    is_ai_analysis_eligible_result,
    parse_ai_review_models,
    validate_ai_analysis_payload,
)
from app.database import Base
from app.main import list_results, run_result_ai_analysis
from app.models import EvaluationResult, EvaluationTestResult, Problem


def build_problem_definition() -> dict:
    return {
        "schemaVersion": "1.0",
        "id": "analysis-demo",
        "title": "Analysis Demo",
        "description": "Build the required page.",
        "course": "COSC 4398",
        "sourcePlatform": "custom",
        "assignmentType": "html-dom",
        "evaluatorType": "browser_qunit_html",
        "language": "html",
        "technologies": ["HTML", "QUnit"],
        "instructions": {
            "studentPrompt": "Return the complete index.html file."
        },
        "files": [
            {
                "path": "index.html",
                "role": "editable",
                "language": "html",
                "content": "<!DOCTYPE html><html><body><main>Starter</main></body></html>\n",
                "includeInPrompt": True,
                "requiredInSubmission": True,
                "preserve": False,
            },
            {
                "path": "layout.css",
                "role": "read_only",
                "language": "css",
                "content": "main { color: lime; }\n",
                "includeInPrompt": True,
                "requiredInSubmission": False,
                "preserve": True,
            },
        ],
        "submissionRules": {
            "mode": "full_editable_file",
            "editablePaths": ["index.html"],
        },
        "runtime": {"environment": "browser"},
        "promptPolicy": {
            "showTests": False,
            "showPointValues": False,
        },
        "tests": [
            {
                "id": "hidden-layout",
                "name": "Hidden Layout",
                "framework": "qunit",
                "path": "tests/layout.js",
                "source": "QUnit.test('hidden', function (assert) { assert.ok(document.querySelector('main')); });",
                "points": 10,
                "visibility": "hidden",
                "timeoutMs": 2000,
                "isolation": "fresh_page",
                "async": False,
                "mutatesGlobals": False,
            }
        ],
        "scoring": {"mode": "test_all_or_nothing", "maximumPoints": 10},
        "metadata": {"difficulty": "easy"},
        "referenceSolution": {
            "source": "zyBooks",
            "files": [
                {
                    "path": "index.html",
                    "language": "html",
                    "content": "<!DOCTYPE html><html><body><main>Reference</main></body></html>\n",
                }
            ],
        },
    }


def build_submitted_files() -> list[dict]:
    return [
        {
            "path": "index.html",
            "language": "html",
            "content": "<!DOCTYPE html><html><body><main>Candidate</main></body></html>\n",
        }
    ]


def build_repetitive_submitted_files() -> list[dict]:
    return [
        {
            "path": "index.js",
            "language": "javascript",
            "content": (
                "function updateWinner() {\n"
                "  document.querySelector(\"#winner\").textContent = \"A\";\n"
                "  document.querySelector(\"#winner\").classList.add(\"active\");\n"
                "}\n"
            ),
        }
    ]


class FakeResponse:
    def __init__(self, status_code: int, payload: Optional[dict] = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class AIAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "mock",
                "AI_REVIEW_PROMPT_VERSION": "ai-code-review-v3",
            },
            clear=False,
        )
        self.env_patcher.start()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.database = Session()
        self.definition = build_problem_definition()
        self.problem = Problem(
            title=self.definition["title"],
            category=self.definition["assignmentType"],
            difficulty="easy",
            language=self.definition["language"],
            description=self.definition["description"],
            starter_code=self.definition["files"][0]["content"],
            required_file="index.html",
            required_function="",
            problem_key=self.definition["id"],
            problem_type=self.definition["evaluatorType"],
            raw_definition_json=json.dumps(self.definition),
        )
        self.database.add(self.problem)
        self.database.commit()
        self.database.refresh(self.problem)

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()
        self.env_patcher.stop()

    def _create_result(
        self,
        *,
        status: str = "Accepted",
        score_earned: Optional[float] = 10.0,
        score_possible: Optional[float] = 10.0,
        score_percentage: Optional[float] = 100.0,
        model_name: str = "gemini-flash-latest",
        comparison_json: Optional[str] = None,
        ai_analysis_status: Optional[str] = None,
        ai_analysis_json: Optional[str] = None,
        ai_analysis_score: Optional[float] = None,
        test_results: Optional[list[dict]] = None,
    ) -> EvaluationResult:
        result = EvaluationResult(
            problem_id=self.problem.id,
            model_name=model_name,
            mode="mock",
            status=status,
            score_earned=score_earned,
            score_possible=score_possible,
            score_percentage=score_percentage,
            comparison_json=comparison_json
            or json.dumps({"submitted_files": build_submitted_files()}),
            ai_analysis_status=ai_analysis_status,
            ai_analysis_json=ai_analysis_json,
            ai_analysis_score=ai_analysis_score,
        )
        for test_result in test_results or []:
            result.test_results.append(
                EvaluationTestResult(
                    test_id=test_result.get("test_id", ""),
                    test_name=test_result.get("name", ""),
                    status=test_result.get("status", ""),
                    points_earned=float(test_result.get("points_earned", 0.0) or 0.0),
                    points_possible=float(
                        test_result.get("points_possible", 0.0) or 0.0
                    ),
                    message=test_result.get("message"),
                    details_json=json.dumps(
                        {
                            "assertions": test_result.get("assertions", []),
                            "console_errors": test_result.get("console_errors", []),
                            "page_errors": test_result.get("page_errors", []),
                            "diagnostics": test_result.get("diagnostics", {}),
                        },
                        ensure_ascii=False,
                    ),
                    duration_ms=test_result.get("duration_ms"),
                )
            )
        self.database.add(result)
        self.database.commit()
        self.database.refresh(result)
        return result

    def _perfect_result_payload(self) -> dict:
        return {
            "status": "Accepted",
            "score_earned": 10.0,
            "score_possible": 10.0,
            "score_percentage": 100.0,
        }

    def test_perfect_result_is_eligible_and_persists_review(self) -> None:
        result = self._create_result()

        response = run_result_ai_analysis(result.id, self.database)
        stored = self.database.get(EvaluationResult, result.id)

        self.assertEqual(response["analysis_status"], "completed")
        self.assertFalse(response["cached"])
        self.assertEqual(response["analysis"]["format"], "plain_text")
        self.assertTrue(response["analysis"]["review_text"])
        self.assertIsNone(response["analysis_score"])
        self.assertEqual(response["reviewer"]["prompt_version"], "ai-code-review-v3")
        self.assertEqual(stored.ai_analysis_status, "completed")
        self.assertIsNotNone(stored.ai_analysis_json)
        self.assertIsNone(stored.ai_analysis_score)
        self.assertIsNotNone(stored.ai_analysis_created_at)

    def test_wrong_answer_result_is_eligible_and_persists_diagnostic_review(self) -> None:
        result = self._create_result(
            status="Wrong Answer",
            score_earned=6.0,
            score_possible=10.0,
            score_percentage=60.0,
            test_results=[
                {
                    "test_id": "hidden-layout",
                    "name": "Hidden Layout",
                    "status": "failed",
                    "points_earned": 0.0,
                    "points_possible": 10.0,
                    "message": "Expected the date select to have id game-date.",
                    "assertions": [
                        {
                            "message": "Expected game-date select to exist.",
                            "expected": "game-date",
                            "actual": "missing",
                        }
                    ],
                }
            ],
        )

        response = run_result_ai_analysis(result.id, self.database)
        stored = self.database.get(EvaluationResult, result.id)

        self.assertEqual(response["analysis_status"], "completed")
        self.assertEqual(response["review_mode"], "wrong_answer_diagnosis")
        self.assertEqual(response["analysis"]["review_mode"], "wrong_answer_diagnosis")
        self.assertIn("Failure Diagnosis", response["analysis"]["review_text"])
        self.assertEqual(
            response["reviewer"]["prompt_version"],
            "ai-code-review-wrong-answer-v1",
        )
        self.assertEqual(stored.ai_analysis_status, "completed")

    def test_wrong_answer_does_not_require_100_percent(self) -> None:
        self.assertTrue(
            is_ai_analysis_eligible_result(
                {
                    "status": "Wrong Answer",
                    "score_earned": 2.0,
                    "score_possible": 10.0,
                    "score_percentage": 20.0,
                }
            )
        )

    def test_format_error_is_rejected(self) -> None:
        result = self._create_result(
            status="FORMAT_ERROR",
            score_earned=None,
            score_possible=None,
            score_percentage=None,
        )

        with self.assertRaises(HTTPException) as context:
            run_result_ai_analysis(result.id, self.database)

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail, AI_ANALYSIS_DISABLED_MESSAGE)

    def test_adapter_error_is_rejected(self) -> None:
        result = self._create_result(
            status="Adapter Error",
            score_earned=None,
            score_possible=None,
            score_percentage=None,
        )

        with self.assertRaises(HTTPException) as context:
            run_result_ai_analysis(result.id, self.database)

        self.assertEqual(context.exception.status_code, 409)

    def test_timed_out_is_rejected(self) -> None:
        result = self._create_result(
            status="Timed Out",
            score_earned=None,
            score_possible=None,
            score_percentage=None,
        )

        with self.assertRaises(HTTPException) as context:
            run_result_ai_analysis(result.id, self.database)

        self.assertEqual(context.exception.status_code, 409)

    def test_interrupted_is_rejected(self) -> None:
        result = self._create_result(
            status="Interrupted",
            score_earned=None,
            score_possible=None,
            score_percentage=None,
        )

        with self.assertRaises(HTTPException) as context:
            run_result_ai_analysis(result.id, self.database)

        self.assertEqual(context.exception.status_code, 409)

    def test_running_is_rejected(self) -> None:
        result = self._create_result(
            status="Running",
            score_earned=None,
            score_possible=None,
            score_percentage=None,
        )

        with self.assertRaises(HTTPException) as context:
            run_result_ai_analysis(result.id, self.database)

        self.assertEqual(context.exception.status_code, 409)

    def test_mock_provider_returns_plain_text_review(self) -> None:
        payload = generate_mock_ai_analysis(
            self.definition,
            build_submitted_files(),
            self.definition["referenceSolution"]["files"],
            self._perfect_result_payload(),
        )

        self.assertEqual(payload["format"], "plain_text")
        self.assertEqual(payload["review_mode"], "accepted_review")
        self.assertIn("Overall assessment", payload["review_text"])
        self.assertEqual(
            payload["reviewer"]["prompt_version"],
            "ai-code-review-v3",
        )

    def test_repeated_request_returns_cached_review(self) -> None:
        result = self._create_result()

        first_response = run_result_ai_analysis(result.id, self.database)
        second_response = run_result_ai_analysis(result.id, self.database)

        self.assertFalse(first_response["cached"])
        self.assertTrue(second_response["cached"])
        self.assertEqual(
            first_response["analysis"]["review_text"],
            second_response["analysis"]["review_text"],
        )

    def test_cached_review_does_not_call_generator_again(self) -> None:
        result = self._create_result()
        mock_payload = generate_mock_ai_analysis(
            self.definition,
            build_submitted_files(),
            self.definition["referenceSolution"]["files"],
            self._perfect_result_payload(),
        )

        with patch("app.main.generate_ai_analysis", return_value=mock_payload) as analysis_mock:
            first_response = run_result_ai_analysis(result.id, self.database)
            second_response = run_result_ai_analysis(result.id, self.database)

        self.assertFalse(first_response["cached"])
        self.assertTrue(second_response["cached"])
        analysis_mock.assert_called_once()

    def test_cached_wrong_answer_review_makes_zero_new_calls(self) -> None:
        result = self._create_result(
            status="Wrong Answer",
            score_earned=7.0,
            score_possible=10.0,
            score_percentage=70.0,
            ai_analysis_status="completed",
            ai_analysis_json=json.dumps(
                {
                    "format": "plain_text",
                    "review_mode": "wrong_answer_diagnosis",
                    "review_text": "Failure Diagnosis\nCached diagnostic review.",
                    "reviewer": {
                        "provider": "openrouter",
                        "requested_model": "openai/gpt-oss-20b:free",
                        "used_model": "openai/gpt-oss-20b:free",
                        "prompt_version": "ai-code-review-wrong-answer-v1",
                        "rubric_version": "ai-code-review-rubric-v1",
                    },
                }
            ),
        )

        with patch("app.main.generate_ai_analysis") as analysis_mock:
            response = run_result_ai_analysis(result.id, self.database)

        analysis_mock.assert_not_called()
        self.assertTrue(response["cached"])
        self.assertEqual(response["review_mode"], "wrong_answer_diagnosis")

    def test_candidate_model_identity_is_not_included_in_reviewer_input(self) -> None:
        result = self._create_result(model_name="mistral:mistral-small-latest")
        review_input = build_ai_analysis_input(
            self.definition,
            build_submitted_files(),
            self.definition["referenceSolution"]["files"],
            {
                "status": result.status,
                "score_earned": result.score_earned,
                "score_possible": result.score_possible,
                "score_percentage": result.score_percentage,
            },
        )

        serialized_input = json.dumps(review_input)
        self.assertNotIn("mistral-small-latest", serialized_input)
        self.assertNotIn("model_name", serialized_input)

    def test_hidden_test_source_is_not_included_in_reviewer_input(self) -> None:
        review_input = build_ai_analysis_input(
            self.definition,
            build_submitted_files(),
            self.definition["referenceSolution"]["files"],
            self._perfect_result_payload(),
        )

        serialized_input = json.dumps(review_input)
        self.assertNotIn("QUnit.test", serialized_input)
        self.assertNotIn("hidden-layout", serialized_input)
        self.assertIn("passed all required functional tests", serialized_input)

    def test_wrong_answer_review_input_includes_only_safe_failed_test_summaries(self) -> None:
        review_input = build_ai_analysis_input(
            self.definition,
            build_submitted_files(),
            self.definition["referenceSolution"]["files"],
            {
                "status": "Wrong Answer",
                "score_earned": 6.0,
                "score_possible": 10.0,
                "score_percentage": 60.0,
                "passed_tests": 3,
                "failed_tests": 1,
                "test_results": [
                    {
                        "test_id": "hidden-layout",
                        "name": "Hidden Layout",
                        "status": "failed",
                        "points_earned": 0.0,
                        "points_possible": 10.0,
                        "message": "Expected the date select to have id game-date.",
                        "assertions": [
                            {
                                "message": "Expected game-date select to exist.",
                                "expected": "game-date",
                                "actual": "missing",
                            }
                        ],
                        "diagnostics": {"hidden_source": "QUnit.test(...)"},
                    }
                ],
            },
            "wrong_answer_diagnosis",
        )

        serialized_input = json.dumps(review_input)
        self.assertIn("Expected the date select to have id game-date.", serialized_input)
        self.assertIn("Expected game-date select to exist.", serialized_input)
        self.assertIn("\"expected\": \"game-date\"", serialized_input)
        self.assertIn("\"actual\": \"missing\"", serialized_input)
        self.assertNotIn("QUnit.test", serialized_input)
        self.assertNotIn("hidden_source", serialized_input)
        self.assertNotIn("model_name", serialized_input)

    def test_historical_results_without_review_remain_valid(self) -> None:
        self._create_result()

        serialized_results = list_results(self.database)

        self.assertEqual(serialized_results[0]["ai_analysis_status"], "not_requested")
        self.assertFalse(serialized_results[0]["ai_analysis_completed"])

    def test_wrong_answer_result_is_marked_available_in_result_serialization(self) -> None:
        self._create_result(
            status="Wrong Answer",
            score_earned=6.0,
            score_possible=10.0,
            score_percentage=60.0,
        )

        serialized_results = list_results(self.database)

        self.assertTrue(serialized_results[0]["ai_analysis_available"])

    def test_functional_score_remains_unchanged(self) -> None:
        result = self._create_result()
        before_score = (result.score_earned, result.score_possible, result.score_percentage)

        run_result_ai_analysis(result.id, self.database)
        stored = self.database.get(EvaluationResult, result.id)

        after_score = (stored.score_earned, stored.score_possible, stored.score_percentage)
        self.assertEqual(before_score, after_score)

    def test_failed_generation_is_persisted_and_can_retry(self) -> None:
        result = self._create_result()

        with patch(
            "app.main.generate_ai_analysis",
            side_effect=RuntimeError("The AI Code Review provider could not be reached."),
        ):
            with self.assertRaises(HTTPException) as context:
                run_result_ai_analysis(result.id, self.database)

        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(
            context.exception.detail,
            "The AI Code Review provider could not be reached.",
        )
        stored = self.database.get(EvaluationResult, result.id)
        self.assertEqual(stored.ai_analysis_status, "failed")
        self.assertEqual(
            stored.ai_analysis_error,
            "The AI Code Review provider could not be reached.",
        )

        retry_response = run_result_ai_analysis(result.id, self.database)
        self.assertEqual(retry_response["analysis_status"], "completed")

    def test_legacy_completed_payload_is_returned_through_compatibility_adapter(self) -> None:
        legacy_payload = {
            "status": "completed",
            "score": 92,
            "summary": "Legacy review summary.",
            "categories": [
                {
                    "id": "requirement_fidelity",
                    "name": "Requirement Fidelity",
                    "points_possible": 25,
                    "points_earned": 23,
                    "explanation": "Legacy category explanation.",
                }
            ],
            "strengths": ["Functionally correct"],
            "improvements": [
                {
                    "issue": "Legacy note",
                    "evidence": "nonexistent snippet",
                    "suggestion": "Legacy suggestion.",
                }
            ],
            "reviewer": {
                "provider": "mock",
                "requested_model": "mock-ai-reviewer",
                "used_model": "mock-ai-reviewer",
                "prompt_version": "ai-analysis-v1",
            },
        }
        result = self._create_result(
            ai_analysis_status="completed",
            ai_analysis_json=json.dumps(legacy_payload),
            ai_analysis_score=92,
        )

        response = run_result_ai_analysis(result.id, self.database)

        self.assertTrue(response["cached"])
        self.assertEqual(response["analysis"]["overall_assessment"], "strong")
        self.assertEqual(
            response["analysis"]["reference_comparison"]["summary"],
            "This stored review predates the current reference-comparison format.",
        )

    def test_openrouter_review_requires_separate_api_key(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "solution-key-only",
                "AI_REVIEW_MODELS": "openai/gpt-oss-20b:free",
            },
            clear=True,
        ):
            with self.assertRaises(ValueError) as context:
                generate_ai_analysis(
                    self.definition,
                    build_submitted_files(),
                    self.definition["referenceSolution"]["files"],
                    self._perfect_result_payload(),
                )

        self.assertIn("AI_REVIEW_OPENROUTER_API_KEY", str(context.exception))

    def test_parse_ai_review_models_skips_non_free_entries_and_blank_values(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_MODELS": " openai/gpt-oss-20b:free , , invalid-model , cohere/north-mini-code:free ",
            },
            clear=True,
        ):
            self.assertEqual(
                parse_ai_review_models(),
                ["openai/gpt-oss-20b:free", "cohere/north-mini-code:free"],
            )

    def test_plain_text_openrouter_response_succeeds_and_persists_reviewer_metadata(self) -> None:
        fake_requests = Mock()
        fake_requests.RequestException = Exception
        fake_requests.post.return_value = FakeResponse(
            200,
            {
                "model": "openai/gpt-oss-20b:free",
                "choices": [
                    {
                        "message": {
                            "content": "Overall assessment\nClear and appropriately scoped."
                        }
                    }
                ],
            },
        )

        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "openrouter",
                "AI_REVIEW_OPENROUTER_API_KEY": "review-key",
                "AI_REVIEW_MODELS": "openai/gpt-oss-20b:free",
            },
            clear=True,
        ):
            with patch("app.ai_analysis.importlib.import_module", return_value=fake_requests):
                payload = generate_ai_analysis(
                    self.definition,
                    build_submitted_files(),
                    self.definition["referenceSolution"]["files"],
                    self._perfect_result_payload(),
        )

        self.assertEqual(fake_requests.post.call_count, 1)
        self.assertEqual(payload["format"], "plain_text")
        self.assertEqual(payload["review_mode"], "accepted_review")
        self.assertEqual(
            payload["review_text"],
            "Overall assessment\nClear and appropriately scoped.",
        )
        self.assertEqual(payload["reviewer"]["requested_model"], "openai/gpt-oss-20b:free")
        self.assertEqual(payload["reviewer"]["used_model"], "openai/gpt-oss-20b:free")
        self.assertEqual(payload["reviewer"]["prompt_version"], "ai-code-review-v3")

    def test_wrong_answer_uses_diagnostic_prompt(self) -> None:
        fake_requests = Mock()
        fake_requests.RequestException = Exception
        fake_requests.post.return_value = FakeResponse(
            200,
            {
                "model": "openai/gpt-oss-20b:free",
                "choices": [
                    {
                        "message": {
                            "content": "Failure Diagnosis\nThe candidate is close but missed a required element."
                        }
                    }
                ],
            },
        )
        wrong_answer_result = {
            "status": "Wrong Answer",
            "score_earned": 6.0,
            "score_possible": 10.0,
            "score_percentage": 60.0,
            "passed_tests": 3,
            "failed_tests": 1,
            "test_results": [
                {
                    "test_id": "hidden-layout",
                    "name": "Hidden Layout",
                    "status": "failed",
                    "points_earned": 0.0,
                    "points_possible": 10.0,
                    "message": "Expected the date select to have id game-date.",
                    "assertions": [{"message": "Expected game-date select to exist."}],
                }
            ],
        }

        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "openrouter",
                "AI_REVIEW_OPENROUTER_API_KEY": "review-key",
                "AI_REVIEW_MODELS": "openai/gpt-oss-20b:free",
            },
            clear=True,
        ):
            with patch("app.ai_analysis.importlib.import_module", return_value=fake_requests):
                payload = generate_ai_analysis(
                    self.definition,
                    build_submitted_files(),
                    self.definition["referenceSolution"]["files"],
                    wrong_answer_result,
                )

        request_payload = fake_requests.post.call_args.kwargs["json"]
        self.assertIn(
            "did not pass all required functional tests",
            request_payload["messages"][0]["content"],
        )
        self.assertIn(
            "visible failed-test summaries",
            request_payload["messages"][1]["content"],
        )
        self.assertEqual(payload["review_mode"], "wrong_answer_diagnosis")
        self.assertEqual(
            payload["reviewer"]["prompt_version"],
            "ai-code-review-wrong-answer-v1",
        )

    def test_surrounding_whitespace_is_trimmed(self) -> None:
        fake_requests = Mock()
        fake_requests.RequestException = Exception
        fake_requests.post.return_value = FakeResponse(
            200,
            {
                "model": "openai/gpt-oss-20b:free",
                "choices": [
                    {"message": {"content": "\n\n  Concise review text.  \n\n"}}
                ],
            },
        )

        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "openrouter",
                "AI_REVIEW_OPENROUTER_API_KEY": "review-key",
                "AI_REVIEW_MODELS": "openai/gpt-oss-20b:free",
            },
            clear=True,
        ):
            with patch("app.ai_analysis.importlib.import_module", return_value=fake_requests):
                payload = generate_ai_analysis(
                    self.definition,
                    build_submitted_files(),
                    self.definition["referenceSolution"]["files"],
                    self._perfect_result_payload(),
                )

        self.assertEqual(payload["review_text"], "Concise review text.")

    def test_empty_response_fails(self) -> None:
        fake_requests = Mock()
        fake_requests.RequestException = Exception
        fake_requests.post.return_value = FakeResponse(
            200,
            {
                "model": "openai/gpt-oss-20b:free",
                "choices": [{"message": {"content": "   \n  "}}],
            },
        )

        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "openrouter",
                "AI_REVIEW_OPENROUTER_API_KEY": "review-key",
                "AI_REVIEW_MODELS": "openai/gpt-oss-20b:free",
            },
            clear=True,
        ):
            with patch("app.ai_analysis.importlib.import_module", return_value=fake_requests):
                with self.assertRaises(ValueError) as context:
                    generate_ai_analysis(
                        self.definition,
                        build_submitted_files(),
                        self.definition["referenceSolution"]["files"],
                        self._perfect_result_payload(),
                    )

        self.assertIn("empty response", str(context.exception))

    def test_no_json_parsing_occurs_for_plain_text(self) -> None:
        fake_requests = Mock()
        fake_requests.RequestException = Exception
        fake_requests.post.return_value = FakeResponse(
            200,
            {
                "model": "openai/gpt-oss-20b:free",
                "choices": [{"message": {"content": "{this is not json, but it is still a useful review}"}}],
            },
        )

        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "openrouter",
                "AI_REVIEW_OPENROUTER_API_KEY": "review-key",
                "AI_REVIEW_MODELS": "openai/gpt-oss-20b:free",
            },
            clear=True,
        ):
            with patch("app.ai_analysis.importlib.import_module", return_value=fake_requests):
                payload = generate_ai_analysis(
                    self.definition,
                    build_submitted_files(),
                    self.definition["referenceSolution"]["files"],
                    self._perfect_result_payload(),
                )

        self.assertEqual(
            payload["review_text"],
            "{this is not json, but it is still a useful review}",
        )

    def test_no_schema_retry_occurs_and_exactly_one_external_call_is_made(self) -> None:
        fake_requests = Mock()
        fake_requests.RequestException = Exception
        fake_requests.post.return_value = FakeResponse(
            200,
            {
                "model": "openai/gpt-oss-20b:free",
                "choices": [{"message": {"content": "{\"overall_score\": 10, \"comments\": [\"Still useful text\"]}"}}],
            },
        )

        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "openrouter",
                "AI_REVIEW_OPENROUTER_API_KEY": "review-key",
                "AI_REVIEW_MODELS": "openai/gpt-oss-20b:free",
            },
            clear=True,
        ):
            with patch("app.ai_analysis.importlib.import_module", return_value=fake_requests):
                payload = generate_ai_analysis(
                    self.definition,
                    build_submitted_files(),
                    self.definition["referenceSolution"]["files"],
                    self._perfect_result_payload(),
                )

        self.assertEqual(fake_requests.post.call_count, 1)
        self.assertIn("overall_score", payload["review_text"])

    def test_cached_review_makes_zero_external_calls(self) -> None:
        result = self._create_result(
            ai_analysis_status="completed",
            ai_analysis_json=json.dumps(
                {
                    "format": "plain_text",
                    "review_text": "Cached review.",
                    "reviewer": {
                        "provider": "openrouter",
                        "requested_model": "openai/gpt-oss-20b:free",
                        "used_model": "openai/gpt-oss-20b:free",
                        "prompt_version": "ai-code-review-v3",
                    },
                }
            ),
        )

        with patch("app.main.generate_ai_analysis") as analysis_mock:
            response = run_result_ai_analysis(result.id, self.database)

        analysis_mock.assert_not_called()
        self.assertTrue(response["cached"])
        self.assertEqual(response["analysis"]["review_text"], "Cached review.")

    def test_old_structured_review_remains_readable(self) -> None:
        legacy_payload = {
            "status": "completed",
            "overall_assessment": "strong",
            "summary": "Structured summary.",
            "categories": [
                {
                    "id": "readability_maintainability",
                    "name": "Readability and Maintainability",
                    "assessment": "strong",
                    "explanation": "Clear implementation.",
                }
            ],
            "strengths": [{"title": "Direct", "explanation": "Focused."}],
            "improvements": [],
            "reference_comparison": {
                "summary": "Both implementations are valid.",
                "meaningful_differences": [],
            },
            "reviewer": {
                "provider": "mock",
                "requested_model": "mock-ai-reviewer",
                "used_model": "mock-ai-reviewer",
                "prompt_version": "ai-code-review-v1",
                "rubric_version": "ai-code-review-rubric-v1",
            },
            "audit": {
                "candidate_content_hash": "candidate-hash",
                "reference_content_hash": "reference-hash",
                "reviewer_output_hash": "output-hash",
                "evidence_verification": {
                    "verified_improvements": 0,
                    "suppressed_improvements": 0,
                    "verified_reference_differences": 0,
                    "suppressed_reference_differences": 0,
                },
            },
        }
        result = self._create_result(
            ai_analysis_status="completed",
            ai_analysis_json=json.dumps(legacy_payload),
        )

        response = run_result_ai_analysis(result.id, self.database)

        self.assertTrue(response["cached"])
        self.assertEqual(response["analysis"]["overall_assessment"], "strong")

    def test_openrouter_malformed_json_envelope_fails_cleanly(self) -> None:
        fake_requests = Mock()
        fake_requests.RequestException = Exception
        response = FakeResponse(
            200,
        )
        response.json = Mock(side_effect=ValueError("bad envelope"))
        fake_requests.post.return_value = response

        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "openrouter",
                "AI_REVIEW_OPENROUTER_API_KEY": "review-key",
                "AI_REVIEW_MODELS": "openai/gpt-oss-20b:free",
            },
            clear=True,
        ):
            with patch("app.ai_analysis.importlib.import_module", return_value=fake_requests):
                with self.assertRaises(ValueError) as context:
                    generate_ai_analysis(
                        self.definition,
                        build_submitted_files(),
                        self.definition["referenceSolution"]["files"],
                        self._perfect_result_payload(),
                    )

        self.assertIn("malformed JSON", str(context.exception))

    def test_system_prompt_allows_no_meaningful_improvements(self) -> None:
        prompt = _build_reviewer_system_prompt()

        self.assertIn(
            "It is a fully acceptable outcome to report no meaningful improvements.",
            prompt,
        )

    def test_system_prompt_forbids_invented_criticism(self) -> None:
        prompt = _build_reviewer_system_prompt()

        self.assertIn("Do not\n  invent criticism to fill a section.", prompt)

    def test_system_prompt_ignores_todo_and_scaffold_comments(self) -> None:
        prompt = _build_reviewer_system_prompt()

        self.assertIn("Ignore removed or absent placeholder/scaffold content", prompt)
        self.assertIn("TODO comments", prompt)

    def test_system_prompt_applies_materiality_threshold_to_style_comments(self) -> None:
        prompt = _build_reviewer_system_prompt()

        self.assertIn(
            "Do not comment on naming, formatting, ordering, or syntax choices unless they\n"
            "  materially harm readability, maintainability, correctness, or efficiency.",
            prompt,
        )
        self.assertIn(
            "\"Different from a common convention\" is not by itself material.",
            prompt,
        )

    def test_prompts_require_independent_assessment_before_reference(self) -> None:
        system_prompt = _build_reviewer_system_prompt()
        review_input = build_ai_analysis_input(
            self.definition,
            build_submitted_files(),
            self.definition["referenceSolution"]["files"],
            self._perfect_result_payload(),
        )
        user_prompt = _build_reviewer_user_prompt(review_input, "accepted_review")

        self.assertIn(
            "Form your assessment of the candidate against the\n"
            "  assignment requirements BEFORE consulting the reference solution.",
            system_prompt,
        )
        self.assertIn(
            "First, assess the candidate independently using only the assignment,",
            user_prompt,
        )

    def test_system_prompt_makes_optional_sections_explicitly_optional(self) -> None:
        prompt = _build_reviewer_system_prompt()

        self.assertIn(
            "Areas for Improvement (omit entirely if none — do not write a placeholder line)",
            prompt,
        )
        self.assertIn(
            "Notable Differences from Reference (omit entirely if none)",
            prompt,
        )

    def test_review_input_orders_reference_solution_files_last(self) -> None:
        review_input = build_ai_analysis_input(
            self.definition,
            build_submitted_files(),
            self.definition["referenceSolution"]["files"],
            self._perfect_result_payload(),
        )

        self.assertEqual(
            list(review_input.keys()),
            [
                "assignment",
                "context_files",
                "candidate_solution_files",
                "reference_solution_files",
            ],
        )

    def test_prompt_version_is_ai_code_review_v3(self) -> None:
        self.assertEqual(AI_ANALYSIS_PROMPT_VERSION, "ai-code-review-v3")

    def test_wrong_answer_prompt_version_is_v1(self) -> None:
        self.assertEqual(
            AI_ANALYSIS_WRONG_ANSWER_PROMPT_VERSION,
            "ai-code-review-wrong-answer-v1",
        )

    def test_wrong_answer_system_prompt_exists(self) -> None:
        prompt = _build_wrong_answer_reviewer_system_prompt()

        self.assertIn("did not pass all required functional tests", prompt)
        self.assertIn("Do not simply say that tests failed.", prompt)
        self.assertIn("Do not force empty sections.", prompt)

    def test_review_mode_detection_is_explicit(self) -> None:
        self.assertEqual(
            determine_ai_analysis_review_mode(self._perfect_result_payload()),
            "accepted_review",
        )
        self.assertEqual(
            determine_ai_analysis_review_mode(
                {
                    "status": "Wrong Answer",
                    "score_earned": 5.0,
                    "score_possible": 10.0,
                    "score_percentage": 50.0,
                }
            ),
            "wrong_answer_diagnosis",
        )
        self.assertIsNone(
            determine_ai_analysis_review_mode(
                {
                    "status": "Adapter Error",
                    "score_earned": None,
                    "score_possible": None,
                    "score_percentage": None,
                }
            )
        )

    def test_candidate_and_reference_hashes_are_present(self) -> None:
        payload = generate_mock_ai_analysis(
            self.definition,
            build_submitted_files(),
            self.definition["referenceSolution"]["files"],
            self._perfect_result_payload(),
        )

        audit = payload["audit"]
        self.assertTrue(audit["candidate_content_hash"])
        self.assertTrue(audit["reference_content_hash"])
        self.assertTrue(audit["reviewer_output_hash"])

    def test_oversized_input_is_rejected_before_provider_call(self) -> None:
        oversized_candidate = [
            {
                "path": "index.html",
                "language": "html",
                "content": "A" * 500,
            }
        ]
        oversized_reference = [
            {
                "path": "index.html",
                "language": "html",
                "content": "B" * 500,
            }
        ]

        with patch.dict(
            "os.environ",
            {
                "AI_REVIEW_PROVIDER": "openrouter",
                "AI_REVIEW_OPENROUTER_API_KEY": "review-key",
                "AI_REVIEW_MODELS": "openai/gpt-oss-20b:free",
                "AI_REVIEW_MAX_INPUT_CHARS": "200",
            },
            clear=True,
        ):
            with patch("app.ai_analysis.importlib.import_module") as import_mock:
                with self.assertRaises(ValueError) as context:
                    generate_ai_analysis(
                        self.definition,
                        oversized_candidate,
                        oversized_reference,
                        self._perfect_result_payload(),
                    )

        import_mock.assert_not_called()
        self.assertIn("exceed the configured AI Code Review input limit", str(context.exception))
