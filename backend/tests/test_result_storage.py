import os
import json
import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.browser_qunit_evaluator import BrowserEvaluationResult, BrowserTestResult
from app.database import Base
from app.main import (
    CompetitionRequest,
    ModelRunRequest,
    get_competition_run,
    get_problem_results,
    judge_sample_solution,
    list_results,
    run_competition,
    run_model_solution,
)
from app.models import EvaluationResult, EvaluationTestResult, Problem
from app.submission_validator import ValidationResult
from tests.problem_bank_fixtures import LEGACY_TIC_TAC_TOE
from tests.provider_fixtures import (
    CSS_REGION_ACCEPTED_AND_FAILED,
    REAL_GEMINI,
    build_generate_solution_side_effect,
)


class ResultStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        TestSession = sessionmaker(bind=self.engine)
        self.database = TestSession()
        self.problem = Problem(
            title="Two Sum",
            category="Arrays",
            difficulty="Easy",
            language="Python",
            description="Return two indices whose values add up to the target.",
            starter_code="def two_sum(numbers, target):\n    pass\n",
            required_file="solution.py",
            required_function="two_sum",
        )
        self.database.add(self.problem)
        self.database.commit()
        self.database.refresh(self.problem)
        self.browser_problem = Problem(
            title="Starting Lineup",
            category="html-dom",
            difficulty="easy",
            language="html",
            description="Browser problem.",
            starter_code="<!DOCTYPE html><html><body></body></html>",
            required_file="index.html",
            required_function="",
            problem_key="starting-lineup-form",
            problem_type="browser_qunit_html",
            raw_definition_json=json.dumps(
                {
                    "schemaVersion": "1.0",
                    "id": "starting-lineup-form",
                    "title": "Starting Lineup",
                    "description": "Browser problem.",
                    "course": "COSC 4398",
                    "sourcePlatform": "custom",
                    "assignmentType": "html-dom",
                    "evaluatorType": "browser_qunit_html",
                    "language": "html",
                    "technologies": ["HTML", "QUnit"],
                    "instructions": {"studentPrompt": "Return the complete index.html file."},
                    "files": [
                        {
                            "path": "index.html",
                            "role": "editable",
                            "language": "html",
                            "content": "<!DOCTYPE html><html><body></body></html>",
                            "includeInPrompt": True,
                            "requiredInSubmission": True,
                            "preserve": False,
                        }
                    ],
                    "submissionRules": {
                        "mode": "full_editable_file",
                        "editablePaths": ["index.html"],
                    },
                    "runtime": {
                        "environment": "browser",
                        "entryFile": "index.html",
                        "browserEngine": "Chromium",
                        "headless": True,
                        "network": "disabled",
                        "processIsolation": "fresh_environment",
                        "testIsolation": "fresh_page",
                        "waitFor": "load",
                        "viewport": {"width": 1280, "height": 720},
                        "setupTimeoutMs": 5000,
                        "individualTestTimeoutMs": 2000,
                        "totalTimeoutMs": 10000,
                    },
                    "promptPolicy": {
                        "showInstructions": True,
                        "showEditableFiles": True,
                        "showReadOnlyFiles": False,
                        "showTests": False,
                        "showPointValues": False,
                        "showEvaluatorType": False,
                    },
                    "tests": [
                        {
                            "id": "browser-pass",
                            "name": "Browser pass",
                            "framework": "qunit",
                            "path": "tests/pass.js",
                            "source": "QUnit.test('Browser pass', function (assert) { assert.ok(true); });",
                            "points": 10,
                            "visibility": "hidden",
                            "timeoutMs": 2000,
                            "isolation": "fresh_page",
                            "async": False,
                            "mutatesGlobals": False,
                        }
                    ],
                    "scoring": {
                        "mode": "test_all_or_nothing",
                        "maximumPoints": 10,
                        "activationStatus": "ready",
                    },
                    "metadata": {},
                }
            ),
        )
        self.css_problem = Problem(
            title=LEGACY_TIC_TAC_TOE["title"],
            category="css",
            difficulty="Easy",
            language="CSS",
            description=LEGACY_TIC_TAC_TOE["description"],
            starter_code=LEGACY_TIC_TAC_TOE["files"][1]["starter_content"],
            required_file="styles.css",
            required_function="",
            problem_key=LEGACY_TIC_TAC_TOE["id"],
            problem_type="css_static_region",
            raw_definition_json=json.dumps(LEGACY_TIC_TAC_TOE),
        )
        self.database.add_all([self.browser_problem, self.css_problem])
        self.database.commit()
        self.database.refresh(self.browser_problem)
        self.database.refresh(self.css_problem)

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def _run_mock_sample(self) -> dict:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            return judge_sample_solution(self.problem.id, self.database)

    def test_judge_sample_saves_result_in_mock_mode(self) -> None:
        response = self._run_mock_sample()
        saved_result = self.database.get(EvaluationResult, response["result_id"])

        self.assertIsNotNone(saved_result)
        self.assertEqual(saved_result.problem_id, self.problem.id)
        self.assertEqual(saved_result.model_name, "hardcoded_sample")
        self.assertEqual(saved_result.mode, "mock")
        self.assertEqual(saved_result.status, "Accepted")
        self.assertEqual(saved_result.stdout, "PASS\n")
        self.assertIsNone(saved_result.comparison_json)

    def test_list_results_returns_saved_results(self) -> None:
        response = self._run_mock_sample()
        results = list_results(self.database)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], response["result_id"])

    def test_problem_results_only_returns_matching_problem(self) -> None:
        self._run_mock_sample()
        other_problem = Problem(
            title="Other",
            category="Test",
            difficulty="Easy",
            language="Python",
            description="Another problem.",
            starter_code="pass\n",
            required_file="solution.py",
            required_function="solve",
        )
        self.database.add(other_problem)
        self.database.commit()
        self.database.refresh(other_problem)
        self.database.add(
            EvaluationResult(
                problem_id=other_problem.id,
                model_name="hardcoded_sample",
                mode="mock",
                status="Accepted",
            )
        )
        self.database.commit()

        results = get_problem_results(self.problem.id, self.database)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["problem_id"], self.problem.id)

    def test_browser_evaluation_persists_scores_and_test_rows(self) -> None:
        browser_result = BrowserEvaluationResult(
            status="Accepted",
            score_earned=10.0,
            score_possible=10.0,
            score_percentage=100.0,
            test_results=[
                BrowserTestResult(
                    test_id="browser-pass",
                    test_name="Browser pass",
                    status="passed",
                    points_possible=10.0,
                    points_earned=10.0,
                    message=None,
                    assertions=[{"result": True, "message": "ok"}],
                    console_errors=[],
                    page_errors=[],
                    diagnostics={"stage": "done"},
                    duration_ms=25,
                )
            ],
            stdout="PASS",
            stderr=None,
            duration_ms=25,
        )

        with patch("app.main.generate_solution") as generate_solution_mock, patch(
            "app.main.validate_universal_submission"
        ) as validate_mock, patch(
            "app.main.playwright_runtime_available",
            return_value=(True, None),
        ), patch(
            "app.main.evaluate_browser_qunit_problem",
            return_value=browser_result,
        ):
            generate_solution_mock.return_value = {
                "model_name": REAL_GEMINI,
                "raw_response": "<!DOCTYPE html><html><body></body></html>",
            }
            validate_mock.return_value = ValidationResult(
                is_valid=True,
                code="<!DOCTYPE html><html><body></body></html>",
                error_message=None,
            )
            response = run_model_solution(
                self.browser_problem.id,
                ModelRunRequest(model_name=REAL_GEMINI),
                self.database,
            )

        saved_result = self.database.get(EvaluationResult, response["result_id"])
        saved_test_results = self.database.query(EvaluationTestResult).filter(
            EvaluationTestResult.evaluation_result_id == saved_result.id
        ).all()

        self.assertEqual(saved_result.score_earned, 10.0)
        self.assertEqual(saved_result.score_possible, 10.0)
        self.assertEqual(saved_result.score_percentage, 100.0)
        self.assertIsNotNone(saved_result.comparison_json)
        self.assertIn('"reference_available": false', saved_result.comparison_json)
        self.assertEqual(response["execution_result"]["passed_tests"], 1)
        self.assertEqual(response["execution_result"]["failed_tests"], 0)
        self.assertEqual(response["execution_result"]["total_tests"], 1)
        self.assertEqual(len(saved_test_results), 1)
        self.assertEqual(saved_test_results[0].test_id, "browser-pass")
        self.assertEqual(saved_test_results[0].status, "passed")
        self.assertIn('"stage": "done"', saved_test_results[0].details_json)

        listed_results = get_problem_results(self.browser_problem.id, self.database)
        self.assertEqual(listed_results[0]["score_earned"], 10.0)
        self.assertEqual(listed_results[0]["passed_tests"], 1)
        self.assertEqual(listed_results[0]["failed_tests"], 0)
        self.assertEqual(listed_results[0]["total_tests"], 1)
        self.assertEqual(listed_results[0]["test_results"][0]["test_id"], "browser-pass")
        self.assertEqual(
            listed_results[0]["test_results"][0]["diagnostics"]["stage"],
            "done",
        )

    def test_browser_competition_persists_scores(self) -> None:
        browser_result = BrowserEvaluationResult(
            status="Wrong Answer",
            score_earned=4.0,
            score_possible=10.0,
            score_percentage=40.0,
            test_results=[
                BrowserTestResult(
                    test_id="browser-pass",
                    test_name="Browser pass",
                    status="failed",
                    points_possible=10.0,
                    points_earned=4.0,
                    message="Expected true, got false.",
                    duration_ms=30,
                )
            ],
            stdout="Score: 4/10",
            stderr="Browser fail: Expected true, got false.",
            duration_ms=30,
        )

        with patch("app.main.generate_solution") as generate_solution_mock, patch(
            "app.main.validate_universal_submission"
        ) as validate_mock, patch(
            "app.main.playwright_runtime_available",
            return_value=(True, None),
        ), patch(
            "app.main.evaluate_browser_qunit_problem",
            return_value=browser_result,
        ):
            generate_solution_mock.return_value = {
                "model_name": REAL_GEMINI,
                "raw_response": "<!DOCTYPE html><html><body></body></html>",
            }
            validate_mock.return_value = ValidationResult(
                is_valid=True,
                code="<!DOCTYPE html><html><body></body></html>",
                error_message=None,
            )
            response = run_competition(
                self.browser_problem.id,
                CompetitionRequest(model_names=[REAL_GEMINI]),
                self.database,
            )
            deadline = time.time() + 2.0
            while time.time() < deadline:
                with sessionmaker(bind=self.engine)() as database:
                    response = get_competition_run(
                        self.browser_problem.id,
                        response["competition_run_id"],
                        database,
                    )
                if response["status"] in {"completed", "completed_with_errors"}:
                    break
                time.sleep(0.02)
            else:
                self.fail("Timed out waiting for competition completion")

        self.assertEqual(response["results"][0]["score_earned"], 4.0)
        self.assertEqual(response["results"][0]["score_possible"], 10.0)
        self.assertEqual(response["results"][0]["score_percentage"], 40.0)
        self.assertEqual(response["results"][0]["passed_tests"], 0)
        self.assertEqual(response["results"][0]["failed_tests"], 1)
        self.assertEqual(response["results"][0]["total_tests"], 1)

    def test_legacy_css_persistence_still_uses_summary_only(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(
                    CSS_REGION_ACCEPTED_AND_FAILED
                ),
            ):
                response = run_model_solution(
                    self.css_problem.id,
                    ModelRunRequest(model_name=REAL_GEMINI),
                    self.database,
                )

        saved_result = self.database.get(EvaluationResult, response["result_id"])
        saved_test_results = self.database.query(EvaluationTestResult).filter(
            EvaluationTestResult.evaluation_result_id == saved_result.id
        ).all()

        self.assertEqual(saved_result.status, "Accepted")
        self.assertIsNone(saved_result.score_earned)
        self.assertIsNone(saved_result.comparison_json)
        self.assertEqual(saved_test_results, [])
        self.assertIsNone(response["execution_result"]["passed_tests"])
        self.assertIsNone(response["execution_result"]["failed_tests"])
        self.assertIsNone(response["execution_result"]["total_tests"])


if __name__ == "__main__":
    unittest.main()
