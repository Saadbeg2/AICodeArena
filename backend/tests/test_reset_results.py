import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import EvaluationResult, EvaluationTestResult, Problem
from scripts.reset_results import clear_evaluation_results, seed_demo_results
from tests.provider_fixtures import REAL_GEMINI, REAL_GROQ


class ResetResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        TestSession = sessionmaker(bind=self.engine)
        self.database = TestSession()

        self.problems = [
            Problem(
                title="Two Sum",
                category="Arrays",
                difficulty="Easy",
                language="Python",
                description="Return two indices.",
                starter_code="def two_sum(numbers, target):\n    pass\n",
                required_file="solution.py",
                required_function="two_sum",
                problem_key="two_sum",
                problem_type="function",
            ),
            Problem(
                title="Fix User Email Bug",
                category="Bug Fixing",
                difficulty="Easy",
                language="Python",
                description="Fix the email helper.",
                starter_code="def get_user_email(user):\n    return user.email.lower()\n",
                required_file="service.py",
                required_function="get_user_email",
                problem_key="fix_user_email",
                problem_type="bug_fix",
            ),
            Problem(
                title="Multiply Numbers",
                category="Math",
                difficulty="Easy",
                language="Python",
                description="Multiply two numbers.",
                starter_code="def multiply_numbers(a, b):\n    pass\n",
                required_file="solution.py",
                required_function="multiply_numbers",
                problem_key="multiply_numbers",
                problem_type="function",
            ),
        ]
        self.database.add_all(self.problems)
        self.database.commit()

        stored_problems = self.database.scalars(
            select(Problem).order_by(Problem.id)
        ).all()
        self.database.add_all(
            [
                EvaluationResult(
                    problem_id=stored_problems[0].id,
                    model_name=REAL_GEMINI,
                    mode="mock",
                    status="Accepted",
                    stdout="PASS\n",
                ),
                EvaluationResult(
                    problem_id=stored_problems[1].id,
                    model_name=REAL_GROQ,
                    mode="mock",
                    status="Runtime Error",
                    stderr="AssertionError",
                ),
            ]
        )
        self.database.commit()
        saved_results = self.database.scalars(
            select(EvaluationResult).order_by(EvaluationResult.id)
        ).all()
        saved_results[0].test_results.append(
            EvaluationTestResult(
                test_id="test-1",
                test_name="Test 1",
                status="passed",
                points_earned=1.0,
                points_possible=1.0,
                message=None,
                details_json="{}",
                duration_ms=1,
            )
        )
        self.database.commit()

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def test_clear_evaluation_results_deletes_only_result_rows(self) -> None:
        deleted_rows = clear_evaluation_results(self.database)
        result_count = self.database.scalar(
            select(func.count()).select_from(EvaluationResult)
        )
        test_result_count = self.database.scalar(
            select(func.count()).select_from(EvaluationTestResult)
        )
        problem_count = self.database.scalar(select(func.count()).select_from(Problem))

        self.assertEqual(deleted_rows, 2)
        self.assertEqual(result_count, 0)
        self.assertEqual(test_result_count, 0)
        self.assertEqual(problem_count, 3)

    def test_seed_demo_results_creates_clean_result_set(self) -> None:
        clear_evaluation_results(self.database)
        inserted_rows = seed_demo_results(self.database)
        saved_results = self.database.scalars(
            select(EvaluationResult).order_by(
                EvaluationResult.problem_id,
                EvaluationResult.model_name,
            )
        ).all()

        self.assertEqual(inserted_rows, 9)
        self.assertEqual(len(saved_results), 9)
        self.assertEqual(saved_results[0].model_name, REAL_GEMINI)
        self.assertEqual(saved_results[1].model_name, REAL_GROQ)
        self.assertEqual(saved_results[2].model_name, "hardcoded_sample")


if __name__ == "__main__":
    unittest.main()
