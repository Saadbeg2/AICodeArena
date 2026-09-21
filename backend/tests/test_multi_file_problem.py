import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import (
    CompetitionRequest,
    ModelRunRequest,
    get_competition_run,
    get_problem_prompt,
    run_competition,
    run_model_solution,
)
from app.models import Problem
from app.seed import seed_database
from tests.provider_fixtures import (
    FIX_USER_EMAIL_ACCEPTED_AND_FAILED,
    REAL_GEMINI,
    REAL_GROQ,
    build_generate_solution_side_effect,
)
from tests.problem_bank_fixtures import LEGACY_FIX_USER_EMAIL, write_problem_bank


class MultiFileProblemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.problem_bank = Path(self.temporary_directory.name)
        write_problem_bank(self.problem_bank, [LEGACY_FIX_USER_EMAIL])
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=self.engine)
        seed_database(self.engine, TestSession, self.problem_bank)
        self.database = TestSession()
        self.problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "fix_user_email")
        )

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def _run_model(self, model_name: str) -> dict:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(
                    FIX_USER_EMAIL_ACCEPTED_AND_FAILED
                ),
            ):
                return run_model_solution(
                    self.problem.id,
                    ModelRunRequest(model_name=model_name),
                    self.database,
                )

    def test_prompt_marks_locked_and_editable_files(self) -> None:
        response = get_problem_prompt(self.problem.id, self.database)

        self.assertIn("user.py (editable: no) [locked]", response.prompt)
        self.assertIn("service.py (editable: yes) [editable]", response.prompt)
        self.assertIn("Editable files: service.py", response.prompt)
        self.assertIn("Locked files: user.py", response.prompt)

    def test_primary_provider_passes_multi_file_problem(self) -> None:
        response = self._run_model(REAL_GEMINI)

        self.assertEqual(response["execution_result"]["status"], "Accepted")
        self.assertEqual(response["execution_result"]["stdout"], "PASS\n")

    def test_secondary_provider_fails_multi_file_problem(self) -> None:
        response = self._run_model(REAL_GROQ)

        self.assertEqual(response["execution_result"]["status"], "Runtime Error")

    def test_competition_runs_all_models_for_multi_file_problem(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch("app.judge0_client.MOCK_TIMEOUT_SECONDS", 0.1):
                with patch(
                    "app.main.generate_solution",
                    side_effect=build_generate_solution_side_effect(
                        FIX_USER_EMAIL_ACCEPTED_AND_FAILED
                    ),
                ):
                    response = run_competition(
                        self.problem.id,
                        CompetitionRequest(),
                        self.database,
                    )
                    deadline = time.time() + 2.0
                    while time.time() < deadline:
                        with sessionmaker(bind=self.engine)() as database:
                            response = get_competition_run(
                                self.problem.id,
                                response["competition_run_id"],
                                database,
                            )
                        if response["status"] in {"completed", "completed_with_errors"}:
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("Timed out waiting for competition completion")

        statuses = {
            result["model_name"]: result["status"]
            for result in response["results"]
        }
        self.assertEqual(statuses[REAL_GEMINI], "Accepted")
        self.assertEqual(statuses[REAL_GROQ], "Runtime Error")


if __name__ == "__main__":
    unittest.main()
