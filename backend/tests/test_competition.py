import os
import threading
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, get_competition_run, get_database, get_model_execution_timeout_seconds
from app.models import CompetitionRun, EvaluationResult, Problem
from tests.provider_fixtures import (
    ACTIVE_MODEL_IDS,
    REAL_GEMINI,
    REAL_GROQ,
    REAL_MISTRAL,
    TWO_SUM_ACCEPTED_AND_FAILED,
    build_generate_solution_side_effect,
)


class CompetitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionFactory = sessionmaker(bind=self.engine)
        self.database = self.SessionFactory()
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

        def override_database():
            database = self.SessionFactory()
            try:
                yield database
            finally:
                database.close()

        app.dependency_overrides[get_database] = override_database
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self.database.close()
        self.engine.dispose()

    def _wait_for(self, predicate, timeout=5.0, interval=0.02):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(interval)
        self.fail("Timed out waiting for condition")

    def _get_run(self, run_id: str) -> dict:
        with self.SessionFactory() as database:
            problem = database.get(Problem, self.problem.id)
            return get_competition_run(problem.id, run_id, database)

    def test_post_returns_202_and_creates_run_before_results_finish(self) -> None:
        release_event = threading.Event()

        def blocked_execution(problem, model_name):
            release_event.wait(1.0)
            return {
                "problem_id": problem.id,
                "model_name": model_name,
                "raw_response": "code",
                "cleaned_code": "code",
                "execution_result": {
                    "status": "Accepted",
                    "stdout": "PASS",
                    "stderr": None,
                    "compile_output": None,
                    "time": "0.01",
                    "memory": None,
                },
                "comparison_result": None,
            }

        with patch("app.main.execute_model_without_persistence", side_effect=blocked_execution):
            response = self.client.post(
                "/problems/{}/run-competition".format(self.problem.id),
                json={"model_names": [REAL_GEMINI, REAL_GROQ]},
            )
            payload = response.json()

            self.assertEqual(response.status_code, 202)
            self.assertEqual(payload["status"], "running")
            self.assertEqual(payload["expected_model_count"], 2)
            self.assertEqual(payload["completed_model_count"], 0)
            self.assertEqual(payload["model_names"], [REAL_GEMINI, REAL_GROQ])
            self.assertEqual(payload["results"], [])

            with self.SessionFactory() as database:
                run = database.get(CompetitionRun, payload["competition_run_id"])
                self.assertIsNotNone(run)
                self.assertEqual(run.status, "running")
                saved_results = database.scalars(
                    select(EvaluationResult).where(
                        EvaluationResult.competition_run_id == payload["competition_run_id"]
                    )
                ).all()
                self.assertEqual(saved_results, [])

            release_event.set()
            completed_run = self._wait_for(
                lambda: self._get_run(payload["competition_run_id"])
                if self._get_run(payload["competition_run_id"])["status"] == "completed"
                else None
            )
            self.assertEqual(completed_run["completed_model_count"], 2)

    def test_exact_run_endpoint_returns_running_with_zero_results(self) -> None:
        release_event = threading.Event()

        def blocked_execution(problem, model_name):
            release_event.wait(1.0)
            return {
                "problem_id": problem.id,
                "model_name": model_name,
                "raw_response": "code",
                "cleaned_code": "code",
                "execution_result": {
                    "status": "Accepted",
                    "stdout": "PASS",
                    "stderr": None,
                    "compile_output": None,
                    "time": "0.01",
                    "memory": None,
                },
                "comparison_result": None,
            }

        with patch("app.main.execute_model_without_persistence", side_effect=blocked_execution):
            response = self.client.post(
                "/problems/{}/run-competition".format(self.problem.id),
                json={"model_names": [REAL_GEMINI]},
            )
            run_id = response.json()["competition_run_id"]

            run_response = self.client.get(
                "/problems/{}/competition-runs/{}".format(self.problem.id, run_id)
            )
            payload = run_response.json()
            self.assertEqual(payload["status"], "running")
            self.assertEqual(payload["expected_model_count"], 1)
            self.assertEqual(payload["completed_model_count"], 0)
            self.assertEqual(payload["results"], [])

            release_event.set()
            self._wait_for(lambda: self._get_run(run_id)["status"] == "completed")

    def test_partial_results_appear_as_models_finish(self) -> None:
        slow_event = threading.Event()

        def mixed_speed_execution(problem, model_name):
            if model_name == REAL_GROQ:
                slow_event.wait(1.0)
            return {
                "problem_id": problem.id,
                "model_name": model_name,
                "raw_response": "code",
                "cleaned_code": "code",
                "execution_result": {
                    "status": "Accepted",
                    "stdout": "PASS",
                    "stderr": None,
                    "compile_output": None,
                    "time": "0.01",
                    "memory": None,
                },
                "comparison_result": None,
            }

        with patch("app.main.execute_model_without_persistence", side_effect=mixed_speed_execution):
            response = self.client.post(
                "/problems/{}/run-competition".format(self.problem.id),
                json={"model_names": [REAL_GEMINI, REAL_GROQ, REAL_MISTRAL]},
            )
            run_id = response.json()["competition_run_id"]

            def partial_run_ready():
                run = self._get_run(run_id)
                if run["completed_model_count"] >= 2:
                    return run
                return None

            partial_run = self._wait_for(
                partial_run_ready
            )
            statuses = {
                result["model_name"]: result["status"]
                for result in partial_run["results"]
            }
            self.assertEqual(statuses[REAL_GEMINI], "Accepted")
            self.assertEqual(statuses[REAL_MISTRAL], "Accepted")
            self.assertEqual(partial_run["status"], "running")

            slow_event.set()
            def final_run_ready():
                run = self._get_run(run_id)
                if run["status"] in {"completed", "completed_with_errors"}:
                    return run
                return None

            final_run = self._wait_for(
                final_run_ready
            )
            self.assertEqual(final_run["completed_model_count"], 3)

    def test_one_model_timeout_while_others_succeed_finishes_with_errors(self) -> None:
        def slow_and_fast(problem, model_name):
            if model_name == REAL_GROQ:
                time.sleep(0.2)
            return {
                "problem_id": problem.id,
                "model_name": model_name,
                "raw_response": "code",
                "cleaned_code": "code",
                "execution_result": {
                    "status": "Accepted",
                    "stdout": "PASS",
                    "stderr": None,
                    "compile_output": None,
                    "time": "0.01",
                    "memory": None,
                },
                "comparison_result": None,
            }

        with patch.dict(os.environ, {"MODEL_EXECUTION_TIMEOUT_SECONDS": "0.05"}, clear=True):
            with patch("app.main.execute_model_without_persistence", side_effect=slow_and_fast):
                response = self.client.post(
                    "/problems/{}/run-competition".format(self.problem.id),
                    json={"model_names": [REAL_GEMINI, REAL_GROQ, REAL_MISTRAL]},
                )
                run_id = response.json()["competition_run_id"]
                final_run = self._wait_for(
                    lambda: self._get_run(run_id)
                    if self._get_run(run_id)["status"] == "completed_with_errors"
                    else None
                )

        statuses = {
            result["model_name"]: result["status"]
            for result in final_run["results"]
        }
        self.assertEqual(statuses[REAL_GEMINI], "Accepted")
        self.assertEqual(statuses[REAL_MISTRAL], "Accepted")
        self.assertEqual(statuses[REAL_GROQ], "Timed Out")
        self.assertEqual(final_run["completed_model_count"], 3)

    def test_latest_run_works_before_any_model_result_exists(self) -> None:
        release_event = threading.Event()

        def blocked_execution(problem, model_name):
            release_event.wait(1.0)
            return {
                "problem_id": problem.id,
                "model_name": model_name,
                "raw_response": "code",
                "cleaned_code": "code",
                "execution_result": {
                    "status": "Accepted",
                    "stdout": "PASS",
                    "stderr": None,
                    "compile_output": None,
                    "time": "0.01",
                    "memory": None,
                },
                "comparison_result": None,
            }

        with patch("app.main.execute_model_without_persistence", side_effect=blocked_execution):
            response = self.client.post(
                "/problems/{}/run-competition".format(self.problem.id),
                json={"model_names": [REAL_GEMINI]},
            )
            run_id = response.json()["competition_run_id"]

            latest_response = self.client.get(
                "/problems/{}/competition-runs/latest".format(self.problem.id)
            )
            payload = latest_response.json()
            self.assertEqual(payload["competition_run_id"], run_id)
            self.assertEqual(payload["status"], "running")
            self.assertEqual(payload["completed_model_count"], 0)

            release_event.set()
            self._wait_for(lambda: self._get_run(run_id)["status"] == "completed")

    def test_runs_from_different_batches_never_mix(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch("app.judge0_client.MOCK_TIMEOUT_SECONDS", 0.1):
                with patch(
                    "app.main.generate_solution",
                    side_effect=build_generate_solution_side_effect(
                        TWO_SUM_ACCEPTED_AND_FAILED
                    ),
                ):
                    first = self.client.post(
                        "/problems/{}/run-competition".format(self.problem.id),
                        json={"model_names": [REAL_GEMINI]},
                    ).json()
                    second = self.client.post(
                        "/problems/{}/run-competition".format(self.problem.id),
                        json={"model_names": [REAL_GROQ, REAL_MISTRAL]},
                    ).json()

                    first_run = self._wait_for(
                        lambda: self._get_run(first["competition_run_id"])
                        if self._get_run(first["competition_run_id"])["completed_model_count"] == 1
                        else None
                    )
                    second_run = self._wait_for(
                        lambda: self._get_run(second["competition_run_id"])
                        if self._get_run(second["competition_run_id"])["completed_model_count"] == 2
                        else None
                    )

        self.assertEqual(
            {result["model_name"] for result in first_run["results"]},
            {REAL_GEMINI},
        )
        self.assertEqual(
            {result["model_name"] for result in second_run["results"]},
            {REAL_GROQ, REAL_MISTRAL},
        )

    def test_background_exceptions_are_isolated(self) -> None:
        def one_failure(problem, model_name):
            if model_name == REAL_GROQ:
                raise ValueError("Provider offline")
            return {
                "problem_id": problem.id,
                "model_name": model_name,
                "raw_response": "code",
                "cleaned_code": "code",
                "execution_result": {
                    "status": "Accepted",
                    "stdout": "PASS",
                    "stderr": None,
                    "compile_output": None,
                    "time": "0.01",
                    "memory": None,
                },
                "comparison_result": None,
            }

        with patch("app.main.execute_model_without_persistence", side_effect=one_failure):
            response = self.client.post(
                "/problems/{}/run-competition".format(self.problem.id),
                json={"model_names": [REAL_GEMINI, REAL_GROQ, REAL_MISTRAL]},
            )
            run_id = response.json()["competition_run_id"]
            final_run = self._wait_for(
                lambda: self._get_run(run_id)
                if self._get_run(run_id)["status"] == "completed_with_errors"
                else None
            )

        statuses = {
            result["model_name"]: result["status"]
            for result in final_run["results"]
        }
        self.assertEqual(statuses[REAL_GEMINI], "Accepted")
        self.assertEqual(statuses[REAL_MISTRAL], "Accepted")
        self.assertEqual(statuses[REAL_GROQ], "Adapter Error")

    def test_every_selected_model_eventually_receives_terminal_row(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch("app.judge0_client.MOCK_TIMEOUT_SECONDS", 0.1):
                with patch(
                    "app.main.generate_solution",
                    side_effect=build_generate_solution_side_effect(
                        TWO_SUM_ACCEPTED_AND_FAILED
                    ),
                ):
                    response = self.client.post(
                        "/problems/{}/run-competition".format(self.problem.id),
                        json={"model_names": ACTIVE_MODEL_IDS},
                    )
                    run_id = response.json()["competition_run_id"]
                    def all_models_finished():
                        run = self._get_run(run_id)
                        if run["completed_model_count"] == len(ACTIVE_MODEL_IDS):
                            return run
                        return None

                    final_run = self._wait_for(
                        all_models_finished
                    )

        terminal_statuses = {
            "Accepted",
            "Wrong Answer",
            "Runtime Error",
            "FORMAT_ERROR",
            "Adapter Error",
            "Timed Out",
            "Interrupted",
        }
        self.assertEqual(len(final_run["results"]), len(ACTIVE_MODEL_IDS))
        self.assertTrue(
            all(result["status"] in terminal_statuses for result in final_run["results"])
        )

    def test_fractional_timeout_configuration_is_supported(self) -> None:
        with patch.dict(
            os.environ,
            {"MODEL_EXECUTION_TIMEOUT_SECONDS": "0.25"},
            clear=True,
        ):
            self.assertEqual(get_model_execution_timeout_seconds(), 0.25)

    def test_invalid_timeout_configuration_falls_back_to_default(self) -> None:
        with patch.dict(
            os.environ,
            {"MODEL_EXECUTION_TIMEOUT_SECONDS": "not-a-number"},
            clear=True,
        ):
            self.assertEqual(get_model_execution_timeout_seconds(), 120.0)

    def test_endpoint_reconciles_stale_running_run(self) -> None:
        stale_run = CompetitionRun(
            id="stale-run",
            problem_id=self.problem.id,
            total_models=2,
            status="running",
            model_names_json='["gemini-flash-latest","groq:llama-3.3-70b-versatile"]',
            created_at=datetime.utcnow() - timedelta(seconds=200),
        )
        self.database.add(stale_run)
        self.database.add(
            EvaluationResult(
                problem_id=self.problem.id,
                model_name=REAL_GEMINI,
                mode="mock",
                status="Accepted",
                stdout="PASS",
                stderr=None,
                compile_output=None,
                time="0.01",
                memory=None,
                competition_run_id="stale-run",
            )
        )
        self.database.commit()

        response = self.client.get(
            f"/problems/{self.problem.id}/competition-runs/stale-run"
        )
        payload = response.json()
        statuses = {
            result["model_name"]: result["status"]
            for result in payload["results"]
        }

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "completed_with_errors")
        self.assertEqual(statuses[REAL_GEMINI], "Accepted")
        self.assertEqual(statuses[REAL_GROQ], "Interrupted")

        refreshed_run = self.database.get(CompetitionRun, "stale-run")
        self.assertEqual(refreshed_run.status, "completed_with_errors")
        self.assertIsNotNone(refreshed_run.completed_at)

    def test_reconciliation_does_not_duplicate_missing_terminal_rows(self) -> None:
        stale_run = CompetitionRun(
            id="stale-run-duplicate-check",
            problem_id=self.problem.id,
            total_models=2,
            status="running",
            model_names_json='["gemini-flash-latest","groq:llama-3.3-70b-versatile"]',
            created_at=datetime.utcnow() - timedelta(seconds=200),
        )
        self.database.add(stale_run)
        self.database.add(
            EvaluationResult(
                problem_id=self.problem.id,
                model_name=REAL_GEMINI,
                mode="mock",
                status="Accepted",
                stdout="PASS",
                stderr=None,
                compile_output=None,
                time="0.01",
                memory=None,
                competition_run_id="stale-run-duplicate-check",
            )
        )
        self.database.commit()

        first = self.client.get(
            f"/problems/{self.problem.id}/competition-runs/stale-run-duplicate-check"
        )
        second = self.client.get(
            f"/problems/{self.problem.id}/competition-runs/stale-run-duplicate-check"
        )

        interrupted_rows = self.database.scalars(
            select(EvaluationResult).where(
                EvaluationResult.competition_run_id == "stale-run-duplicate-check",
                EvaluationResult.model_name == REAL_GROQ,
            )
        ).all()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(interrupted_rows), 1)
        self.assertEqual(interrupted_rows[0].status, "Interrupted")

    def test_lifespan_calls_stale_run_reconciliation_on_startup(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()

        with patch("app.main.seed_database"), patch(
            "app.main.reconcile_stale_competition_runs"
        ) as reconcile_mock, patch("app.main.SessionLocal", self.SessionFactory):
            with TestClient(app):
                pass

        reconcile_mock.assert_called()


if __name__ == "__main__":
    unittest.main()
