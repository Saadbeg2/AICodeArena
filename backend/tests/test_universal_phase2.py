import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.browser_qunit_evaluator import playwright_runtime_available
from app.main import ModelRunRequest, run_model_solution
from app.models import EvaluationResult, Problem
from app.seed import seed_database
from tests.provider_fixtures import (
    REAL_GEMINI,
    STARTING_LINEUP_ACCEPTED_AND_FAILED,
    TWO_SUM_FORMAT_BAD,
    build_generate_solution_side_effect,
)


class UniversalPhase2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(bind=self.engine)
        seed_database(self.engine, self.session_factory)
        self.database = self.session_factory()
        self.starting_lineup_problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "starting-lineup-form")
        )

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def test_universal_format_bad_model_returns_format_error(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(TWO_SUM_FORMAT_BAD),
            ):
                response = run_model_solution(
                    self.starting_lineup_problem.id,
                    ModelRunRequest(model_name=REAL_GEMINI),
                    self.database,
                )

        self.assertEqual(response["execution_result"]["status"], "FORMAT_ERROR")
        self.assertIsNone(response["cleaned_code"])
        self.assertIn("Markdown fences", response["execution_result"]["stderr"])

        saved_result = self.database.get(EvaluationResult, response["result_id"])
        self.assertIsNotNone(saved_result)
        self.assertEqual(saved_result.status, "FORMAT_ERROR")

    def test_valid_universal_submission_does_not_enter_legacy_execution(self) -> None:
        available, _ = playwright_runtime_available()

        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch("app.main.run_python_code") as mock_run_python_code:
                with patch("app.main.evaluate_css_static_region") as mock_css_evaluator:
                    with patch(
                        "app.main.generate_solution",
                        side_effect=build_generate_solution_side_effect(
                            STARTING_LINEUP_ACCEPTED_AND_FAILED
                        ),
                    ):
                        if available:
                            response = run_model_solution(
                                self.starting_lineup_problem.id,
                                ModelRunRequest(model_name=REAL_GEMINI),
                                self.database,
                            )
                            self.assertEqual(
                                response["execution_result"]["status"],
                                "Accepted",
                            )
                        else:
                            with self.assertRaises(HTTPException) as raised:
                                run_model_solution(
                                    self.starting_lineup_problem.id,
                                    ModelRunRequest(model_name=REAL_GEMINI),
                                    self.database,
                                )

                            self.assertEqual(raised.exception.status_code, 503)
                            self.assertIn(
                                "Browser evaluation is not available",
                                raised.exception.detail,
                            )

        mock_run_python_code.assert_not_called()
        mock_css_evaluator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
