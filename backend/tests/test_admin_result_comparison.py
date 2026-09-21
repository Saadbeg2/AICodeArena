import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, get_database
from app.models import EvaluationResult, Problem
from app.seed import seed_database
from tests.provider_fixtures import REAL_GEMINI


class ResultComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(bind=self.engine)
        seed_database(self.engine, self.session_factory)
        self.database = self.session_factory()

        def override_database():
            try:
                yield self.database
            finally:
                pass

        app.dependency_overrides[get_database] = override_database
        self.client = TestClient(app)
        self.problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "starting-lineup-form")
        )
        self.reference_content = json.loads(self.problem.raw_definition_json)[
            "referenceSolution"
        ]["files"][0]["content"]

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        self.database.close()
        self.engine.dispose()

    def _create_result(self, comparison_json=None) -> EvaluationResult:
        saved_result = EvaluationResult(
            problem_id=self.problem.id,
            model_name=REAL_GEMINI,
            mode="mock",
            status="Accepted",
            stdout="PASS\n",
            score_earned=10.0,
            score_possible=10.0,
            score_percentage=100.0,
            comparison_json=comparison_json,
        )
        self.database.add(saved_result)
        self.database.commit()
        self.database.refresh(saved_result)
        return saved_result

    def test_result_comparison_returns_comparison_data(self) -> None:
        comparison = {
            "reference_available": True,
            "reference_source": "zyBooks",
            "compared_file_paths": ["index.html"],
            "missing_submitted_files": [],
            "unexpected_submitted_files": [],
            "files": [
                {
                    "path": "index.html",
                    "language": "html",
                    "exact_match": False,
                    "normalized_match": True,
                    "added_line_count": 1,
                    "removed_line_count": 1,
                    "changed_line_count": 1,
                    "unified_diff": [
                        "--- reference/index.html",
                        "+++ submission/index.html",
                        "-secret reference line",
                        "+student line",
                    ],
                }
            ],
            "overall_exact_match": False,
            "overall_normalized_match": True,
            "submitted_files": [
                {
                    "path": "index.html",
                    "language": "html",
                    "content": "<html><body>student solution</body></html>",
                }
            ],
        }
        saved_result = self._create_result(
            json.dumps(comparison, ensure_ascii=False)
        )
        response = self.client.get(f"/results/{saved_result.id}/comparison")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["result_id"], saved_result.id)
        self.assertEqual(body["problem_id"], self.problem.id)
        self.assertEqual(body["model_name"], REAL_GEMINI)
        self.assertTrue(body["comparison_available"])
        self.assertEqual(body["comparison"]["compared_file_paths"], ["index.html"])
        self.assertTrue(body["comparison"]["files"][0]["unified_diff_available"])
        self.assertEqual(body["comparison"]["files"][0]["unified_diff_line_count"], 4)
        self.assertNotIn("unified_diff", body["comparison"]["files"][0])
        self.assertEqual(len(body["reference_files"]), 1)
        self.assertEqual(body["reference_files"][0]["path"], "index.html")
        self.assertEqual(len(body["submitted_files"]), 1)
        self.assertEqual(body["submitted_files"][0]["path"], "index.html")
        self.assertIn("student solution", body["submitted_files"][0]["content"])

    def test_nonexistent_result_returns_404(self) -> None:
        response = self.client.get("/results/999999/comparison")

        self.assertEqual(response.status_code, 404)

    def test_null_comparison_json_returns_404(self) -> None:
        saved_result = self._create_result(None)
        response = self.client.get(f"/results/{saved_result.id}/comparison")

        self.assertEqual(response.status_code, 404)

    def test_malformed_comparison_json_is_handled_safely(self) -> None:
        saved_result = self._create_result("{not-valid-json")
        response = self.client.get(f"/results/{saved_result.id}/comparison")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["comparison_available"])
        self.assertIsNone(body["comparison"])
        self.assertIn("malformed", body["message"].lower())
        self.assertNotIn("{not-valid-json", response.text)

    def test_public_results_endpoint_still_does_not_expose_comparison_data(self) -> None:
        self._create_result(json.dumps({"reference_available": True}))

        response = self.client.get("/results")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("comparison_json", response.text)
        self.assertNotIn("comparison", response.text)

    def test_leaderboard_still_does_not_expose_comparison_data(self) -> None:
        self._create_result(json.dumps({"reference_available": True}))

        response = self.client.get(f"/leaderboard?problem_id={self.problem.id}")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("comparison_json", response.text)
        self.assertNotIn("referenceSolution", response.text)

    def test_problem_endpoints_still_do_not_expose_reference_solution(self) -> None:
        problems_response = self.client.get("/problems")
        problem_response = self.client.get(f"/problems/{self.problem.id}")

        self.assertEqual(problems_response.status_code, 200)
        self.assertEqual(problem_response.status_code, 200)
        self.assertNotIn("referenceSolution", problems_response.text)
        self.assertNotIn("referenceSolution", problem_response.text)
        self.assertNotIn(self.reference_content, problems_response.text)
        self.assertNotIn(self.reference_content, problem_response.text)
