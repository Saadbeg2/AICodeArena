import json
import unittest
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import get_leaderboard
from app.models import EvaluationResult, EvaluationTestResult, Problem
from tests.provider_fixtures import REAL_GEMINI, REAL_GROQ, REAL_MISTRAL


class LeaderboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        TestSession = sessionmaker(bind=self.engine)
        self.database = TestSession()
        self.problem = self._add_problem("Two Sum")

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def _add_problem(self, title: str) -> Problem:
        problem = Problem(
            title=title,
            category="Arrays",
            difficulty="Easy",
            language="Python",
            description="Test problem.",
            starter_code="pass\n",
            required_file="solution.py",
            required_function="solve",
        )
        self.database.add(problem)
        self.database.commit()
        self.database.refresh(problem)
        return problem

    def _add_result(
        self,
        problem_id: int,
        model_name: str,
        status: str,
        execution_time: Optional[str] = None,
        score_earned: Optional[float] = None,
        score_possible: Optional[float] = None,
        score_percentage: Optional[float] = None,
        test_statuses: Optional[list[str]] = None,
    ) -> EvaluationResult:
        result = EvaluationResult(
            problem_id=problem_id,
            model_name=model_name,
            mode="mock",
            status=status,
            time=execution_time,
            score_earned=score_earned,
            score_possible=score_possible,
            score_percentage=score_percentage,
        )
        for index, test_status in enumerate(test_statuses or [], start=1):
            result.test_results.append(
                EvaluationTestResult(
                    test_id="test_{0}".format(index),
                    test_name="Test {0}".format(index),
                    status=test_status,
                    points_earned=1.0 if test_status == "passed" else 0.0,
                    points_possible=1.0,
                    message=None,
                    details_json="{}",
                    duration_ms=5,
                )
            )
        self.database.add(result)
        self.database.commit()
        self.database.refresh(result)
        return result

    def test_accepted_model_ranks_above_failed_and_timeout_models(self) -> None:
        self._add_result(self.problem.id, REAL_GROQ, "Runtime Error", "0.010")
        self._add_result(
            self.problem.id,
            "hardcoded_sample",
            "Time Limit Exceeded",
            "5.000",
        )
        self._add_result(self.problem.id, REAL_GEMINI, "Accepted", "0.032")

        response = get_leaderboard(None, self.database)
        leaderboard = response["leaderboard"]

        self.assertEqual(
            [entry["model_name"] for entry in leaderboard],
            [REAL_GEMINI, REAL_GROQ, "hardcoded_sample"],
        )
        self.assertEqual(leaderboard[0]["rank"], 1)
        self.assertEqual(leaderboard[0]["accepted_runs"], 1)
        self.assertEqual(leaderboard[0]["latest_status"], "Accepted")
        self.assertEqual(leaderboard[0]["best_time"], "0.032")

    def test_problem_filter_only_uses_matching_results(self) -> None:
        other_problem = self._add_problem("Other Problem")
        self._add_result(self.problem.id, "model_one", "Accepted", "0.020")
        self._add_result(other_problem.id, "model_two", "Accepted", "0.010")

        response = get_leaderboard(self.problem.id, self.database)

        self.assertEqual(response["problem_id"], self.problem.id)
        self.assertEqual(len(response["leaderboard"]), 1)
        self.assertEqual(response["leaderboard"][0]["model_name"], "model_one")

    def test_empty_results_returns_empty_leaderboard(self) -> None:
        response = get_leaderboard(None, self.database)

        self.assertIsNone(response["problem_id"])
        self.assertEqual(response["leaderboard"], [])

    def test_browser_scores_rank_above_legacy_status_counts(self) -> None:
        self._add_result(
            self.problem.id,
            "browser_model",
            "Wrong Answer",
            "0.200",
            score_earned=9.0,
            score_possible=10.0,
            score_percentage=90.0,
        )
        self._add_result(
            self.problem.id,
            "legacy_model",
            "Accepted",
            "0.010",
        )

        response = get_leaderboard(self.problem.id, self.database)

        self.assertEqual(response["leaderboard"][0]["model_name"], "browser_model")
        self.assertEqual(response["leaderboard"][0]["score_percentage"], 90.0)

    def test_browser_score_tie_breaks_use_score_earned_then_time(self) -> None:
        self._add_result(
            self.problem.id,
            "higher_earned",
            "Accepted",
            "0.050",
            score_earned=9.5,
            score_possible=10.0,
            score_percentage=95.0,
        )
        self._add_result(
            self.problem.id,
            "faster_same_percent",
            "Accepted",
            "0.020",
            score_earned=9.0,
            score_possible=9.4736842105,
            score_percentage=95.0,
        )
        self._add_result(
            self.problem.id,
            "slower_same_everything",
            "Accepted",
            "0.040",
            score_earned=9.0,
            score_possible=9.4736842105,
            score_percentage=95.0,
        )

        response = get_leaderboard(self.problem.id, self.database)
        ordered_models = [entry["model_name"] for entry in response["leaderboard"]]

        self.assertEqual(
            ordered_models,
            ["higher_earned", "faster_same_percent", "slower_same_everything"],
        )

    def test_row_uses_best_result_even_after_later_worse_attempt(self) -> None:
        best_result = self._add_result(
            self.problem.id,
            REAL_GEMINI,
            "Accepted",
            "0.050",
            score_earned=10.0,
            score_possible=10.0,
            score_percentage=100.0,
            test_statuses=["passed", "passed"],
        )
        self._add_result(
            self.problem.id,
            REAL_GEMINI,
            "Wrong Answer",
            "0.020",
            score_earned=6.0,
            score_possible=10.0,
            score_percentage=60.0,
            test_statuses=["passed", "failed"],
        )

        response = get_leaderboard(self.problem.id, self.database)
        entry = response["leaderboard"][0]

        self.assertEqual(entry["result_id"], best_result.id)
        self.assertEqual(entry["latest_status"], "Accepted")
        self.assertEqual(entry["score_earned"], 10.0)
        self.assertEqual(entry["score_percentage"], 100.0)
        self.assertEqual(entry["passed_tests"], 2)
        self.assertEqual(entry["total_tests"], 2)
        self.assertEqual(entry["time"], "0.050")

    def test_equal_score_tie_breaks_to_newest_result(self) -> None:
        older = self._add_result(
            self.problem.id,
            REAL_GEMINI,
            "Accepted",
            "0.050",
            score_earned=8.0,
            score_possible=10.0,
            score_percentage=80.0,
            test_statuses=["passed", "failed"],
        )
        newer = self._add_result(
            self.problem.id,
            REAL_GEMINI,
            "Accepted",
            "0.050",
            score_earned=8.0,
            score_possible=10.0,
            score_percentage=80.0,
            test_statuses=["passed", "failed"],
        )

        response = get_leaderboard(self.problem.id, self.database)
        entry = response["leaderboard"][0]

        self.assertNotEqual(older.id, newer.id)
        self.assertEqual(entry["result_id"], newer.id)

    def test_test_counts_are_not_summed_across_attempts(self) -> None:
        self._add_result(
            self.problem.id,
            REAL_GEMINI,
            "Accepted",
            "0.050",
            score_earned=10.0,
            score_possible=10.0,
            score_percentage=100.0,
            test_statuses=["passed", "passed"],
        )
        self._add_result(
            self.problem.id,
            REAL_GEMINI,
            "Wrong Answer",
            "0.030",
            score_earned=4.0,
            score_possible=10.0,
            score_percentage=40.0,
            test_statuses=["passed", "failed", "failed"],
        )

        response = get_leaderboard(self.problem.id, self.database)
        entry = response["leaderboard"][0]

        self.assertEqual(entry["passed_tests"], 2)
        self.assertEqual(entry["failed_tests"], 0)
        self.assertEqual(entry["total_tests"], 2)

    def test_multiple_problems_do_not_mix_model_rows(self) -> None:
        other_problem = self._add_problem("Other Problem")
        self._add_result(
            self.problem.id,
            REAL_GEMINI,
            "Accepted",
            "0.050",
            score_earned=10.0,
            score_possible=10.0,
            score_percentage=100.0,
            test_statuses=["passed"],
        )
        other_result = self._add_result(
            other_problem.id,
            REAL_GEMINI,
            "Wrong Answer",
            "0.020",
            score_earned=1.0,
            score_possible=10.0,
            score_percentage=10.0,
            test_statuses=["failed", "failed", "failed"],
        )

        response = get_leaderboard(self.problem.id, self.database)
        entry = response["leaderboard"][0]

        self.assertEqual(response["problem_id"], self.problem.id)
        self.assertNotEqual(entry["result_id"], other_result.id)
        self.assertEqual(entry["score_percentage"], 100.0)

    def test_same_problem_models_use_same_scored_test_denominator(self) -> None:
        definition = {
            "schemaVersion": "1.0",
            "id": "starting_lineup_form",
            "title": self.problem.title,
            "description": "Browser problem.",
            "course": "CS",
            "sourcePlatform": "custom",
            "assignmentType": "html",
            "evaluatorType": "browser_qunit_html",
            "language": "html",
            "technologies": ["html"],
            "instructions": {"studentPrompt": "Build the page."},
            "files": [
                {
                    "path": "index.html",
                    "role": "editable",
                    "language": "html",
                    "content": "<html></html>",
                    "includeInPrompt": True,
                    "requiredInSubmission": True,
                    "preserve": False,
                }
            ],
            "submissionRules": {
                "mode": "full_editable_file",
                "editablePaths": ["index.html"],
            },
            "runtime": {"totalTimeoutMs": 30000},
            "promptPolicy": {},
            "tests": [
                {
                    "id": "t1",
                    "name": "Test 1",
                    "framework": "qunit",
                    "path": "tests/t1.js",
                    "source": "QUnit.test('t1', assert => assert.ok(true));",
                    "points": 2,
                    "visibility": "hidden",
                    "timeoutMs": 1000,
                    "isolation": "page",
                    "async": False,
                    "mutatesGlobals": False,
                },
                {
                    "id": "t2",
                    "name": "Test 2",
                    "framework": "qunit",
                    "path": "tests/t2.js",
                    "source": "QUnit.test('t2', assert => assert.ok(true));",
                    "points": 3,
                    "visibility": "hidden",
                    "timeoutMs": 1000,
                    "isolation": "page",
                    "async": False,
                    "mutatesGlobals": False,
                },
            ],
            "scoring": {"mode": "test_all_or_nothing", "maximumPoints": 5},
            "metadata": {"difficulty": "easy"},
        }
        self.problem.problem_type = "browser_qunit_html"
        self.problem.raw_definition_json = json.dumps(definition)
        self.database.commit()

        gemini_result = EvaluationResult(
            problem_id=self.problem.id,
            model_name=REAL_GEMINI,
            mode="mock",
            status="Accepted",
            time="0.050",
            score_earned=5.0,
            score_possible=5.0,
            score_percentage=100.0,
        )
        gemini_result.test_results.extend(
            [
                EvaluationTestResult(
                    test_id="t1",
                    test_name="Test 1",
                    status="passed",
                    points_earned=2.0,
                    points_possible=2.0,
                    message=None,
                    details_json="{}",
                    duration_ms=1,
                ),
                EvaluationTestResult(
                    test_id="t2",
                    test_name="Test 2",
                    status="passed",
                    points_earned=3.0,
                    points_possible=3.0,
                    message=None,
                    details_json="{}",
                    duration_ms=1,
                ),
            ]
        )
        groq_result = EvaluationResult(
            problem_id=self.problem.id,
            model_name=REAL_GROQ,
            mode="mock",
            status="Wrong Answer",
            time="0.060",
            score_earned=2.0,
            score_possible=5.0,
            score_percentage=40.0,
        )
        groq_result.test_results.extend(
            [
                EvaluationTestResult(
                    test_id="t1",
                    test_name="Test 1",
                    status="passed",
                    points_earned=2.0,
                    points_possible=2.0,
                    message=None,
                    details_json="{}",
                    duration_ms=1,
                ),
                EvaluationTestResult(
                    test_id="t2",
                    test_name="Test 2",
                    status="failed",
                    points_earned=0.0,
                    points_possible=3.0,
                    message=None,
                    details_json="{}",
                    duration_ms=1,
                ),
            ]
        )
        mistral_result = EvaluationResult(
            problem_id=self.problem.id,
            model_name=REAL_MISTRAL,
            mode="mock",
            status="Wrong Answer",
            time="0.070",
            score_earned=0.0,
            score_possible=5.0,
            score_percentage=0.0,
        )
        mistral_result.test_results.extend(
            [
                EvaluationTestResult(
                    test_id="t1",
                    test_name="Test 1",
                    status="failed",
                    points_earned=0.0,
                    points_possible=2.0,
                    message=None,
                    details_json="{}",
                    duration_ms=1,
                ),
                EvaluationTestResult(
                    test_id="t2",
                    test_name="Test 2",
                    status="failed",
                    points_earned=0.0,
                    points_possible=3.0,
                    message=None,
                    details_json="{}",
                    duration_ms=1,
                ),
            ]
        )
        self.database.add_all([gemini_result, groq_result, mistral_result])
        self.database.commit()
        self.database.refresh(gemini_result)
        self.database.refresh(groq_result)
        self.database.refresh(mistral_result)

        gemini_result.test_results.append(
            EvaluationTestResult(
                test_id="old-browser-test",
                test_name="Old Browser Test",
                status="failed",
                points_earned=0.0,
                points_possible=1.0,
                message=None,
                details_json="{}",
                duration_ms=1,
            )
        )
        groq_result.test_results.append(
            EvaluationTestResult(
                test_id="helper-check",
                test_name="Helper Check",
                status="passed",
                points_earned=0.0,
                points_possible=0.0,
                message=None,
                details_json="{}",
                duration_ms=1,
            )
        )
        mistral_result.test_results.append(
            EvaluationTestResult(
                test_id="another-old-test",
                test_name="Another Old Test",
                status="passed",
                points_earned=1.0,
                points_possible=1.0,
                message=None,
                details_json="{}",
                duration_ms=1,
            )
        )
        self.database.commit()

        response = get_leaderboard(self.problem.id, self.database)
        rows = {entry["model_name"]: entry for entry in response["leaderboard"]}

        self.assertEqual(rows[REAL_GEMINI]["passed_tests"], 2)
        self.assertEqual(rows[REAL_GEMINI]["total_tests"], 2)
        self.assertEqual(rows[REAL_GROQ]["passed_tests"], 1)
        self.assertEqual(rows[REAL_GROQ]["total_tests"], 2)
        self.assertEqual(rows[REAL_MISTRAL]["passed_tests"], 0)
        self.assertEqual(rows[REAL_MISTRAL]["total_tests"], 2)


if __name__ == "__main__":
    unittest.main()
