import json
import os
import unittest
from typing import Optional
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.legacy.quality_grader import (
    FUNCTIONAL_GATE_REASON,
    evaluate_solution_quality,
)
from app.main import (
    build_leaderboard,
    execute_model_without_persistence,
    save_evaluation_result,
    serialize_evaluation_result,
)
from app.models import EvaluationResult, Problem
from app.reference_comparison import compare_submitted_files_to_reference


QUALITY_DISABLED_REASON = "Deterministic quality grading is disabled."


def build_html_problem_definition() -> dict:
    return {
        "schemaVersion": "1.0",
        "id": "quality_html_problem",
        "title": "Quality HTML Problem",
        "description": "Render the required form.",
        "course": "COSC 4398",
        "sourcePlatform": "custom",
        "assignmentType": "html-dom",
        "evaluatorType": "browser_qunit_html",
        "language": "html",
        "technologies": ["HTML"],
        "instructions": {"studentPrompt": "Return index.html"},
        "files": [
            {
                "path": "index.html",
                "role": "editable",
                "language": "html",
                "content": "<!DOCTYPE html><html><body><form id=\"signup\"><input id=\"email\" /><button>Save</button></form></body></html>",
                "includeInPrompt": True,
                "requiredInSubmission": True,
                "preserve": False,
            }
        ],
        "submissionRules": {
            "mode": "full_editable_file",
            "editablePaths": ["index.html"],
        },
        "runtime": {"totalTimeoutMs": 10000},
        "promptPolicy": {},
        "tests": [
            {
                "id": "layout",
                "name": "Layout",
                "framework": "qunit",
                "path": "tests/layout.js",
                "source": "QUnit.test('layout', assert => assert.ok(true));",
                "points": 10,
                "visibility": "hidden",
                "timeoutMs": 1000,
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
                    "content": "<!DOCTYPE html><html><body><form id=\"signup\"><input id=\"email\" /><button>Save</button></form></body></html>",
                }
            ],
        },
    }


def build_perfect_execution_result() -> dict:
    return {
        "status": "Accepted",
        "score_earned": 10.0,
        "score_possible": 10.0,
        "score_percentage": 100.0,
        "test_results": [
            {
                "test_id": "layout",
                "name": "Layout",
                "status": "passed",
                "points_earned": 10.0,
                "points_possible": 10.0,
                "message": None,
                "assertions": [],
                "console_errors": [],
                "page_errors": [],
                "diagnostics": {},
                "duration_ms": 10,
            }
        ],
    }


class LegacyDeterministicQualityGraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = build_html_problem_definition()

    def _evaluate(self, submitted_content: str, execution_result: Optional[dict] = None) -> dict:
        execution = execution_result or build_perfect_execution_result()
        submitted_files = {"index.html": submitted_content}
        comparison = compare_submitted_files_to_reference(self.definition, submitted_files)
        return evaluate_solution_quality(
            self.definition,
            submitted_files,
            execution,
            comparison,
        )

    def test_functional_score_below_full_skips_quality(self) -> None:
        result = self._evaluate(
            "<!DOCTYPE html><html><body></body></html>",
            execution_result={
                "status": "Wrong Answer",
                "score_earned": 6.0,
                "score_possible": 10.0,
                "score_percentage": 60.0,
                "test_results": [],
            },
        )

        self.assertEqual(result["quality_status"], "not_evaluated")
        self.assertIsNone(result["quality_score"])
        self.assertEqual(result["competition_score"], 60.0)
        self.assertEqual(result["quality_reason"], FUNCTIONAL_GATE_REASON)

    def test_perfect_functional_score_triggers_quality(self) -> None:
        result = self._evaluate(
            self.definition["referenceSolution"]["files"][0]["content"]
        )

        self.assertEqual(result["quality_status"], "evaluated")
        self.assertIsNotNone(result["quality_score"])
        self.assertIsNotNone(result["quality_breakdown"])


class QualityDisabledPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.database = Session()
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

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def _execute(self, raw_response: str) -> dict:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True), patch(
            "app.main.generate_solution",
            return_value={
                "model_name": "gemini-flash-latest",
                "raw_response": raw_response,
            },
        ):
            return execute_model_without_persistence(
                self.problem,
                "gemini-flash-latest",
            )

    def test_deterministic_quality_grader_is_not_called(self) -> None:
        with patch(
            "app.legacy.quality_grader.evaluate_solution_quality",
            side_effect=AssertionError("legacy quality grader should not be called"),
        ) as quality_mock:
            model_execution = self._execute(
                "def two_sum(numbers, target):\n"
                "    seen = {}\n"
                "    for index, number in enumerate(numbers):\n"
                "        needed = target - number\n"
                "        if needed in seen:\n"
                "            return [seen[needed], index]\n"
                "        seen[number] = index\n"
                "    return []\n"
            )

        self.assertEqual(model_execution["execution_result"]["status"], "Accepted")
        quality_mock.assert_not_called()

    def test_new_perfect_functional_result_is_marked_disabled(self) -> None:
        model_execution = self._execute(
            "def two_sum(numbers, target):\n"
            "    seen = {}\n"
            "    for index, number in enumerate(numbers):\n"
            "        needed = target - number\n"
            "        if needed in seen:\n"
            "            return [seen[needed], index]\n"
            "        seen[number] = index\n"
            "    return []\n"
        )

        result = model_execution["execution_result"]
        self.assertEqual(result["quality_status"], "disabled")
        self.assertIsNone(result["quality_score"])
        self.assertIsNone(result["competition_score"])
        self.assertIsNone(result["quality_breakdown"])
        self.assertEqual(result["quality_reason"], QUALITY_DISABLED_REASON)

    def test_new_imperfect_functional_result_is_also_marked_disabled(self) -> None:
        model_execution = self._execute(
            "def two_sum(numbers, target):\n"
            "    return [0, 0]\n"
        )

        result = model_execution["execution_result"]
        self.assertNotEqual(result["status"], "Accepted")
        self.assertEqual(result["quality_status"], "disabled")
        self.assertIsNone(result["quality_score"])
        self.assertIsNone(result["competition_score"])
        self.assertEqual(result["quality_reason"], QUALITY_DISABLED_REASON)


class QualityPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.database = Session()
        self.problem = Problem(
            title="Quality HTML Problem",
            category="html-dom",
            difficulty="easy",
            language="html",
            description="Render the required form.",
            starter_code="<html></html>",
            required_file="index.html",
            required_function="",
            problem_key="quality_html_problem",
            problem_type="browser_qunit_html",
            raw_definition_json=json.dumps(build_html_problem_definition()),
        )
        self.database.add(self.problem)
        self.database.commit()
        self.database.refresh(self.problem)

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def test_new_results_persist_disabled_quality_state(self) -> None:
        result = save_evaluation_result(
            self.database,
            self.problem.id,
            "gemini-flash-latest",
            {
                "status": "Accepted",
                "stdout": "PASS",
                "stderr": None,
                "compile_output": None,
                "time": "0.050",
                "memory": None,
                "score_earned": 10.0,
                "score_possible": 10.0,
                "score_percentage": 100.0,
                "quality_status": "disabled",
                "quality_score": None,
                "competition_score": None,
                "quality_breakdown": None,
                "quality_reason": QUALITY_DISABLED_REASON,
                "test_results": [
                    {
                        "test_id": "layout",
                        "name": "Layout",
                        "status": "passed",
                        "points_earned": 10.0,
                        "points_possible": 10.0,
                        "message": None,
                        "assertions": [],
                        "console_errors": [],
                        "page_errors": [],
                        "diagnostics": {},
                        "duration_ms": 10,
                    }
                ],
            },
        )

        serialized = serialize_evaluation_result(result, self.problem)
        self.assertEqual(serialized["quality_status"], "disabled")
        self.assertIsNone(serialized["quality_score"])
        self.assertIsNone(serialized["competition_score"])
        self.assertIsNone(serialized["quality_breakdown"])
        self.assertEqual(serialized["quality_reason"], QUALITY_DISABLED_REASON)

    def test_backward_compatibility_for_historical_rows_with_quality_data(self) -> None:
        historical = EvaluationResult(
            problem_id=self.problem.id,
            model_name="groq:llama-3.3-70b-versatile",
            mode="live",
            status="Accepted",
            score_earned=10.0,
            score_possible=10.0,
            score_percentage=100.0,
            quality_status="evaluated",
            quality_score=95.0,
            competition_score=99.5,
            quality_breakdown_json=json.dumps(
                {
                    "conciseness": {
                        "earned": 40,
                        "possible": 40,
                        "status": "evaluated",
                    }
                }
            ),
            quality_reason=None,
        )
        self.database.add(historical)
        self.database.commit()
        self.database.refresh(historical)

        serialized = serialize_evaluation_result(historical, self.problem)
        self.assertEqual(serialized["quality_status"], "evaluated")
        self.assertEqual(serialized["quality_score"], 95.0)
        self.assertEqual(serialized["competition_score"], 99.5)
        self.assertIn("conciseness", serialized["quality_breakdown"])

    def test_old_rows_without_quality_data_remain_compatible(self) -> None:
        legacy = EvaluationResult(
            problem_id=self.problem.id,
            model_name="mistral:mistral-small-latest",
            mode="live",
            status="Accepted",
            score_earned=10.0,
            score_possible=10.0,
            score_percentage=100.0,
        )
        self.database.add(legacy)
        self.database.commit()
        self.database.refresh(legacy)

        serialized = serialize_evaluation_result(legacy, self.problem)
        self.assertEqual(serialized["quality_status"], "unavailable")
        self.assertIsNone(serialized["quality_score"])
        self.assertIsNone(serialized["quality_breakdown"])
        self.assertIsNone(serialized["competition_score"])

    def test_leaderboard_orders_by_functional_score_not_quality(self) -> None:
        slower_higher_quality = EvaluationResult(
            problem_id=self.problem.id,
            model_name="gemini-flash-latest",
            mode="live",
            status="Accepted",
            score_earned=10.0,
            score_possible=10.0,
            score_percentage=100.0,
            time="0.200",
            quality_status="evaluated",
            quality_score=99.0,
            competition_score=99.9,
        )
        faster_lower_quality = EvaluationResult(
            problem_id=self.problem.id,
            model_name="groq:llama-3.3-70b-versatile",
            mode="live",
            status="Accepted",
            score_earned=10.0,
            score_possible=10.0,
            score_percentage=100.0,
            time="0.100",
            quality_status="evaluated",
            quality_score=70.0,
            competition_score=97.0,
        )
        lower_functional = EvaluationResult(
            problem_id=self.problem.id,
            model_name="mistral:mistral-small-latest",
            mode="live",
            status="Wrong Answer",
            score_earned=9.0,
            score_possible=10.0,
            score_percentage=90.0,
            quality_status="evaluated",
            quality_score=100.0,
            competition_score=100.0,
        )
        self.database.add_all([slower_higher_quality, faster_lower_quality, lower_functional])
        self.database.commit()

        leaderboard = build_leaderboard(
            [slower_higher_quality, faster_lower_quality, lower_functional],
            {self.problem.id: self.problem},
        )
        self.assertEqual(
            [entry["model_name"] for entry in leaderboard],
            [
                "groq:llama-3.3-70b-versatile",
                "gemini-flash-latest",
                "mistral:mistral-small-latest",
            ],
        )


if __name__ == "__main__":
    unittest.main()
