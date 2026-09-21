import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.browser_qunit_evaluator import BrowserEvaluationResult
from app.database import Base
from app.main import ModelRunRequest, get_leaderboard, list_results, run_model_solution
from app.models import EvaluationResult, Problem
from app.reference_comparison import (
    build_submitted_editable_files,
    compare_submitted_files_to_reference,
)
from app.seed import seed_database
from tests.problem_bank_fixtures import LEGACY_TWO_SUM
from tests.provider_fixtures import REAL_GEMINI


class ReferenceComparisonServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.single_file_definition = {
            "schemaVersion": "1.0",
            "id": "demo-html",
            "title": "Demo HTML",
            "description": "Demo",
            "course": "COSC 4398",
            "sourcePlatform": "custom",
            "assignmentType": "html-form",
            "evaluatorType": "browser_qunit_html",
            "language": "html",
            "technologies": ["HTML"],
            "instructions": {"studentPrompt": "Return index.html"},
            "files": [
                {
                    "path": "index.html",
                    "role": "editable",
                    "language": "html",
                    "content": "<!DOCTYPE html>\n<html>\n<body>\n</body>\n</html>\n",
                    "includeInPrompt": True,
                    "requiredInSubmission": True,
                    "preserve": False,
                }
            ],
            "referenceSolution": {
                "source": "zyBooks",
                "files": [
                    {
                        "path": "index.html",
                        "language": "html",
                        "content": "<!DOCTYPE html>\n<html>\n<body>\n</body>\n</html>\n",
                    }
                ],
            },
            "submissionRules": {
                "mode": "full_editable_file",
                "editablePaths": ["index.html"],
            },
            "runtime": {"environment": "browser"},
            "promptPolicy": {"showTests": False},
            "tests": [],
            "scoring": {"mode": "test_all_or_nothing", "maximumPoints": 10},
            "metadata": {},
        }
        self.multi_file_definition = {
            **self.single_file_definition,
            "id": "multi-file",
            "files": [
                {
                    "path": "index.html",
                    "role": "editable",
                    "language": "html",
                    "content": "<html></html>\n",
                    "includeInPrompt": True,
                    "requiredInSubmission": True,
                    "preserve": False,
                },
                {
                    "path": "quote.js",
                    "role": "editable",
                    "language": "javascript",
                    "content": "console.log('hi');\n",
                    "includeInPrompt": True,
                    "requiredInSubmission": True,
                    "preserve": False,
                },
            ],
            "referenceSolution": {
                "source": "zyBooks",
                "files": [
                    {
                        "path": "index.html",
                        "language": "html",
                        "content": "<html></html>\n",
                    },
                    {
                        "path": "quote.js",
                        "language": "javascript",
                        "content": "console.log('hi');\n",
                    },
                ],
            },
            "submissionRules": {
                "mode": "full_editable_file",
                "editablePaths": ["index.html"],
            },
        }

    def test_exact_match(self) -> None:
        result = compare_submitted_files_to_reference(
            self.single_file_definition,
            {"index.html": "<!DOCTYPE html>\n<html>\n<body>\n</body>\n</html>\n"},
        )

        self.assertTrue(result["reference_available"])
        self.assertTrue(result["overall_exact_match"])
        self.assertTrue(result["overall_normalized_match"])
        self.assertEqual(result["missing_submitted_files"], [])
        self.assertEqual(result["unexpected_submitted_files"], [])
        self.assertEqual(result["files"][0]["added_line_count"], 0)
        self.assertEqual(result["files"][0]["removed_line_count"], 0)
        self.assertEqual(result["files"][0]["changed_line_count"], 0)

    def test_trailing_whitespace_only_difference(self) -> None:
        result = compare_submitted_files_to_reference(
            self.single_file_definition,
            {"index.html": "<!DOCTYPE html>   \n<html>\n<body>   \n</body>\n</html>\n"},
        )

        self.assertFalse(result["overall_exact_match"])
        self.assertTrue(result["overall_normalized_match"])
        self.assertEqual(result["files"][0]["added_line_count"], 0)
        self.assertEqual(result["files"][0]["removed_line_count"], 0)
        self.assertEqual(result["files"][0]["changed_line_count"], 0)

    def test_final_newline_only_difference(self) -> None:
        result = compare_submitted_files_to_reference(
            self.single_file_definition,
            {"index.html": "<!DOCTYPE html>\n<html>\n<body>\n</body>\n</html>"},
        )

        self.assertFalse(result["overall_exact_match"])
        self.assertTrue(result["overall_normalized_match"])

    def test_substantive_line_change(self) -> None:
        result = compare_submitted_files_to_reference(
            self.single_file_definition,
            {"index.html": "<!DOCTYPE html>\n<html>\n<body>\n<p>Changed</p>\n</body>\n</html>\n"},
        )

        self.assertFalse(result["overall_exact_match"])
        self.assertFalse(result["overall_normalized_match"])
        self.assertGreater(
            result["files"][0]["changed_line_count"]
            + result["files"][0]["added_line_count"]
            + result["files"][0]["removed_line_count"],
            0,
        )
        self.assertTrue(result["files"][0]["unified_diff"])

    def test_missing_submitted_file(self) -> None:
        result = compare_submitted_files_to_reference(
            self.single_file_definition,
            {},
        )

        self.assertEqual(result["missing_submitted_files"], ["index.html"])
        self.assertFalse(result["overall_exact_match"])
        self.assertFalse(result["overall_normalized_match"])

    def test_unexpected_file(self) -> None:
        result = compare_submitted_files_to_reference(
            self.single_file_definition,
            {
                "index.html": "<!DOCTYPE html>\n<html>\n<body>\n</body>\n</html>\n",
                "extra.js": "console.log('extra');\n",
            },
        )

        self.assertEqual(result["unexpected_submitted_files"], ["extra.js"])
        self.assertFalse(result["overall_exact_match"])
        self.assertFalse(result["overall_normalized_match"])

    def test_problem_without_reference_solution(self) -> None:
        definition = dict(self.single_file_definition)
        definition.pop("referenceSolution")

        result = compare_submitted_files_to_reference(
            definition,
            {"index.html": "<!DOCTYPE html>\n<html>\n<body>\n</body>\n</html>\n"},
        )

        self.assertFalse(result["reference_available"])
        self.assertEqual(result["compared_file_paths"], [])

    def test_multi_file_comparison(self) -> None:
        result = compare_submitted_files_to_reference(
            self.multi_file_definition,
            {
                "index.html": "<html></html>\n",
                "quote.js": "console.log('bye');\n",
            },
        )

        self.assertEqual(result["compared_file_paths"], ["index.html", "quote.js"])
        self.assertTrue(result["files"][0]["exact_match"])
        self.assertFalse(result["files"][1]["normalized_match"])

    def test_build_submitted_editable_files_maps_single_editable_path(self) -> None:
        submitted_files = build_submitted_editable_files(
            self.single_file_definition,
            "<!DOCTYPE html>\n<html></html>\n",
        )

        self.assertEqual(
            submitted_files,
            {"index.html": "<!DOCTYPE html>\n<html></html>\n"},
        )


class ReferenceComparisonPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(bind=self.engine)
        seed_database(self.engine, self.session_factory)
        self.database = self.session_factory()
        self.problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "starting-lineup-form")
        )
        self.legacy_problem = Problem(
            title=LEGACY_TWO_SUM["title"],
            category="Arrays",
            difficulty="Easy",
            language="Python",
            description=LEGACY_TWO_SUM["description"],
            starter_code=LEGACY_TWO_SUM["files"][0]["starter_content"],
            required_file=LEGACY_TWO_SUM["files"][0]["filename"],
            required_function="two_sum",
            problem_key=LEGACY_TWO_SUM["id"],
            problem_type=LEGACY_TWO_SUM["type"],
            raw_definition_json=json.dumps(LEGACY_TWO_SUM),
        )
        self.database.add(self.legacy_problem)
        self.database.commit()
        self.database.refresh(self.legacy_problem)

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def test_legacy_records_remain_compatible_when_comparison_is_missing(self) -> None:
        self.database.add(
            EvaluationResult(
                problem_id=self.legacy_problem.id,
                model_name="legacy_model",
                mode="mock",
                status="Accepted",
                stdout="PASS\n",
            )
        )
        self.database.commit()

        results = list_results(self.database)
        legacy_entry = next(
            result for result in results if result["problem_id"] == self.legacy_problem.id
        )

        self.assertEqual(legacy_entry["model_name"], "legacy_model")
        self.assertNotIn("comparison", legacy_entry)

    def test_public_results_and_leaderboard_do_not_leak_comparison(self) -> None:
        comparison = {
            "reference_available": True,
            "compared_file_paths": ["index.html"],
            "missing_submitted_files": [],
            "unexpected_submitted_files": [],
            "files": [
                {
                    "path": "index.html",
                    "exact_match": False,
                    "normalized_match": True,
                    "added_line_count": 0,
                    "removed_line_count": 0,
                    "changed_line_count": 0,
                    "unified_diff": [],
                }
            ],
            "overall_exact_match": False,
            "overall_normalized_match": True,
        }
        self.database.add(
            EvaluationResult(
                problem_id=self.problem.id,
                model_name="browser_model",
                mode="mock",
                status="Accepted",
                stdout="PASS\n",
                score_earned=10.0,
                score_possible=10.0,
                score_percentage=100.0,
                comparison_json=json.dumps(comparison, ensure_ascii=False),
            )
        )
        self.database.commit()

        results = list_results(self.database)
        leaderboard = get_leaderboard(self.problem.id, self.database)

        results_text = str(results)
        leaderboard_text = str(leaderboard)

        self.assertNotIn("comparison", results_text)
        self.assertNotIn("referenceSolution", results_text)
        self.assertNotIn("comparison", leaderboard_text)
        self.assertNotIn("referenceSolution", leaderboard_text)

    def test_run_model_persists_internal_reference_comparison(self) -> None:
        submission = (
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            "   <title>Starting Lineup</title>\n"
            "   <link rel=\"stylesheet\" href=\"styles.css\">\n"
            "</head>\n<body>\n   <h1>Starting Lineup</h1>\n"
            "   <p>close enough</p>\n</body>\n</html>\n"
        )
        request = ModelRunRequest(model_name=REAL_GEMINI)

        with patch(
            "app.main.generate_solution",
            return_value={
                "model_name": REAL_GEMINI,
                "raw_response": submission,
                "cleaned_code": submission,
            },
        ), patch(
            "app.main.playwright_runtime_available",
            return_value=(True, None),
        ), patch(
            "app.main.evaluate_browser_qunit_problem",
            return_value=BrowserEvaluationResult(
                status="Accepted",
                score_earned=10.0,
                score_possible=10.0,
                score_percentage=100.0,
                test_results=[],
                stdout="PASS\n",
                stderr=None,
                duration_ms=25,
            ),
        ):
            response = run_model_solution(self.problem.id, request, self.database)

        saved_result = self.database.get(EvaluationResult, response["result_id"])
        self.assertIsNotNone(saved_result)
        self.assertIsNotNone(saved_result.comparison_json)

        comparison = json.loads(saved_result.comparison_json)
        self.assertTrue(comparison["reference_available"])
        self.assertEqual(comparison["compared_file_paths"], ["index.html"])
        self.assertFalse(comparison["overall_exact_match"])
        self.assertFalse(comparison["overall_normalized_match"])
