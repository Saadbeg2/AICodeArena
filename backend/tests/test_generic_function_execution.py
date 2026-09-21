import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import (
    CompetitionRequest,
    ModelRunRequest,
    get_competition_run,
    get_leaderboard,
    run_competition,
    run_model_solution,
)
from app.models import Problem
from app.seed import seed_database
from app.test_harness import build_generic_function_test_harness
from tests.provider_fixtures import (
    ACTIVE_MODEL_IDS,
    MULTIPLY_ACCEPTED_AND_FAILED,
    REAL_GEMINI,
    REAL_GROQ,
    TWO_SUM_FORMAT_BAD,
    build_generate_solution_side_effect,
)
from tests.problem_bank_fixtures import LEGACY_MULTIPLY_NUMBERS, write_problem_bank


CORRECT_MULTIPLY_SOLUTION = """def multiply_numbers(a, b):
    return a * b"""

INCORRECT_MULTIPLY_SOLUTION = """def multiply_numbers(a, b):
    return a + b"""


class GenericFunctionExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.problem_bank = Path(self.temporary_directory.name)
        write_problem_bank(self.problem_bank, [LEGACY_MULTIPLY_NUMBERS])
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=self.engine)
        seed_database(self.engine, TestSession, self.problem_bank)
        self.database = TestSession()
        self.problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "multiply_numbers")
        )
        self.assertEqual(self.problem.id, 1)

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def _run_model(self, model_name: str) -> dict:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(
                    {
                        REAL_GEMINI: MULTIPLY_ACCEPTED_AND_FAILED[REAL_GEMINI],
                        REAL_GROQ: MULTIPLY_ACCEPTED_AND_FAILED[REAL_GROQ],
                    }
                ),
            ):
                return run_model_solution(
                    self.problem.id,
                    ModelRunRequest(model_name=model_name),
                    self.database,
                )

    def _run_competition(self) -> dict:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch("app.judge0_client.MOCK_TIMEOUT_SECONDS", 0.1):
                with patch(
                    "app.main.generate_solution",
                    side_effect=build_generate_solution_side_effect(
                        MULTIPLY_ACCEPTED_AND_FAILED
                    ),
                ):
                    response = run_competition(
                        self.problem.id,
                        CompetitionRequest(),
                        self.database,
                    )
                    return self._wait_for_competition_completion(response["competition_run_id"])

    def _wait_for_competition_completion(self, run_id: str, timeout: float = 2.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with sessionmaker(bind=self.engine)() as database:
                response = get_competition_run(self.problem.id, run_id, database)
            if response["status"] in {"completed", "completed_with_errors"}:
                return response
            time.sleep(0.02)
        self.fail("Timed out waiting for competition completion")

    def test_generic_harness_contains_solution_and_json_tests(self) -> None:
        harness = build_generic_function_test_harness(
            self.problem,
            CORRECT_MULTIPLY_SOLUTION,
        )

        self.assertIn(CORRECT_MULTIPLY_SOLUTION, harness)
        self.assertIn("multiply_numbers(**arguments)", harness)
        self.assertIn("'a': -4", harness)
        self.assertIn("'expected': -20", harness)

    def test_generic_harness_passes_correct_solution(self) -> None:
        harness = build_generic_function_test_harness(
            self.problem,
            CORRECT_MULTIPLY_SOLUTION,
        )
        output = io.StringIO()

        with redirect_stdout(output):
            exec(harness, {})

        self.assertEqual(output.getvalue().strip(), "PASS")

    def test_generic_harness_fails_incorrect_solution(self) -> None:
        harness = build_generic_function_test_harness(
            self.problem,
            INCORRECT_MULTIPLY_SOLUTION,
        )

        with self.assertRaisesRegex(AssertionError, "expected"):
            exec(harness, {})

    def test_run_model_good_returns_accepted_and_pass(self) -> None:
        response = self._run_model(REAL_GEMINI)

        self.assertEqual(response["execution_result"]["status"], "Accepted")
        self.assertEqual(response["execution_result"]["stdout"], "PASS\n")
        self.assertIn("multiply_numbers", response["cleaned_code"])

    def test_run_model_format_bad_returns_format_error(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(
                    {REAL_GEMINI: TWO_SUM_FORMAT_BAD[REAL_GEMINI]}
                ),
            ):
                response = run_model_solution(
                    self.problem.id,
                    ModelRunRequest(model_name=REAL_GEMINI),
                    self.database,
                )

        self.assertEqual(response["execution_result"]["status"], "FORMAT_ERROR")
        self.assertIsNone(response["cleaned_code"])

    def test_run_model_bad_returns_failure(self) -> None:
        response = self._run_model(REAL_GROQ)

        self.assertEqual(response["execution_result"]["status"], "Runtime Error")

    def test_competition_runs_generic_function_problem(self) -> None:
        response = self._run_competition()
        statuses = {
            result["model_name"]: result["status"]
            for result in response["results"]
        }

        self.assertEqual(statuses[REAL_GEMINI], "Accepted")
        self.assertEqual(statuses[REAL_GROQ], "Runtime Error")

    def test_leaderboard_ranks_good_model_first(self) -> None:
        self._run_competition()

        response = get_leaderboard(self.problem.id, self.database)

        self.assertEqual(response["leaderboard"][0]["model_name"], REAL_GEMINI)
        self.assertEqual(response["leaderboard"][0]["accepted_runs"], 1)


if __name__ == "__main__":
    unittest.main()
