import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.css_static_checker import (
    assemble_css_region_submission,
    evaluate_css_static_region,
)
from app.main import (
    CompetitionRequest,
    ModelRunRequest,
    get_competition_run,
    get_leaderboard,
    get_problem_prompt,
    run_competition,
    run_model_solution,
)
from app.models import Problem
from app.seed import seed_database
from tests.provider_fixtures import (
    CSS_REGION_ACCEPTED_AND_FAILED,
    REAL_GEMINI,
    REAL_GROQ,
    TWO_SUM_FORMAT_BAD,
    build_generate_solution_side_effect,
)
from tests.problem_bank_fixtures import LEGACY_TIC_TAC_TOE, write_problem_bank


CSS_GOOD = """display: grid;
grid-template-columns: repeat(3, 100px);
grid-template-rows: repeat(3,100px);
gap: 10px;
justify-content: center;"""


class CssStaticProblemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.problem_bank = Path(self.temporary_directory.name)
        write_problem_bank(self.problem_bank, [LEGACY_TIC_TAC_TOE])
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=self.engine)
        seed_database(self.engine, TestSession, self.problem_bank)
        self.database = TestSession()
        self.problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "tic_tac_toe_board")
        )
        self.assertEqual(self.problem.id, 1)

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def _wait_for_competition_completion(self, run_id: str, timeout: float = 2.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with sessionmaker(bind=self.engine)() as database:
                response = get_competition_run(self.problem.id, run_id, database)
            if response["status"] in {"completed", "completed_with_errors"}:
                return response
            time.sleep(0.02)
        self.fail("Timed out waiting for competition completion")

    def _run_model(self, model_name: str) -> dict:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(
                    CSS_REGION_ACCEPTED_AND_FAILED
                ),
            ):
                return run_model_solution(
                    self.problem.id,
                    ModelRunRequest(model_name=model_name),
                    self.database,
                )

    def test_prompt_explains_css_todo_region(self) -> None:
        response = get_problem_prompt(self.problem.id, self.database)

        self.assertIn("index.html is read-only", response.prompt)
        self.assertIn("Only complete the TODO region inside the #board rule", response.prompt)
        self.assertIn("Return only CSS declarations for the #board rule", response.prompt)
        self.assertIn("Do not include #board { }.", response.prompt)

    def test_css_assembly_inserts_declarations_into_todo_region(self) -> None:
        completed_css = assemble_css_region_submission(self.problem, CSS_GOOD)

        self.assertIn("display: grid;", completed_css)
        self.assertIn("#board {", completed_css)
        self.assertNotIn("TODO: Add your solution here", completed_css)

    def test_css_checker_accepts_complete_solution(self) -> None:
        result = evaluate_css_static_region(self.problem, CSS_GOOD)

        self.assertEqual(result["status"], "Accepted")
        self.assertEqual(result["stdout"], "PASS")

    def test_run_model_good_returns_accepted(self) -> None:
        response = self._run_model(REAL_GEMINI)

        self.assertEqual(response["execution_result"]["status"], "Accepted")
        self.assertEqual(response["execution_result"]["stdout"], "PASS")
        self.assertIn("display: grid;", response["cleaned_code"])

    def test_run_model_bad_returns_wrong_answer(self) -> None:
        response = self._run_model(REAL_GROQ)

        self.assertEqual(response["execution_result"]["status"], "Wrong Answer")
        self.assertIn("Missing required declaration", response["execution_result"]["stderr"])

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

    def test_competition_runs_css_problem(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(
                    CSS_REGION_ACCEPTED_AND_FAILED
                ),
            ):
                response = run_competition(
                    self.problem.id,
                    CompetitionRequest(),
                    self.database,
                )
                response = self._wait_for_competition_completion(response["competition_run_id"])
        statuses = {
            result["model_name"]: result["status"]
            for result in response["results"]
        }
        self.assertEqual(statuses[REAL_GEMINI], "Accepted")
        self.assertEqual(statuses[REAL_GROQ], "Wrong Answer")

    def test_leaderboard_ranks_good_css_model_first(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(
                    CSS_REGION_ACCEPTED_AND_FAILED
                ),
            ):
                response = run_competition(
                    self.problem.id,
                    CompetitionRequest(),
                    self.database,
                )
                self._wait_for_competition_completion(response["competition_run_id"])
        response = get_leaderboard(self.problem.id, self.database)

        self.assertEqual(response["leaderboard"][0]["model_name"], REAL_GEMINI)


if __name__ == "__main__":
    unittest.main()
