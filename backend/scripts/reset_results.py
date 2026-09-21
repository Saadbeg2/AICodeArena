import argparse
import sys
from pathlib import Path
from typing import List

from sqlalchemy import func, select
from sqlalchemy.orm import Session


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import EvaluationResult, EvaluationTestResult, Problem  # noqa: E402
from app.model_adapters import get_default_competition_models  # noqa: E402
from app.seed import seed_database  # noqa: E402


def clear_evaluation_results(database: Session) -> int:
    """Delete saved evaluation history while preserving problems."""
    database.query(EvaluationTestResult).delete(synchronize_session=False)
    deleted_rows = database.query(EvaluationResult).delete(synchronize_session=False)
    database.commit()
    return deleted_rows


def build_demo_results(problem_ids: List[int]) -> List[EvaluationResult]:
    """Create a small clean result set for demos and screenshots."""
    demo_rows = []
    competition_models = get_default_competition_models()

    for problem_id in problem_ids:
        demo_rows.append(
            EvaluationResult(
                problem_id=problem_id,
                model_name="hardcoded_sample",
                mode="mock",
                status="Accepted",
                stdout="PASS\n",
                stderr="",
                compile_output=None,
                time="0.028",
                memory=None,
            )
        )

        if competition_models:
            demo_rows.append(
                EvaluationResult(
                    problem_id=problem_id,
                    model_name=competition_models[0],
                    mode="live",
                    status="Accepted",
                    stdout="PASS\n",
                    stderr="",
                    compile_output=None,
                    time="0.032",
                    memory=None,
                )
            )

        if len(competition_models) > 1:
            demo_rows.append(
                EvaluationResult(
                    problem_id=problem_id,
                    model_name=competition_models[1],
                    mode="live",
                    status="Runtime Error",
                    stdout="",
                    stderr="AssertionError: Demo failure",
                    compile_output=None,
                    time="0.041",
                    memory=None,
                )
            )

    return demo_rows


def seed_demo_results(database: Session) -> int:
    """Insert a clean demo result set for available problems."""
    problem_ids = list(
        database.scalars(select(Problem.id).order_by(Problem.id)).all()
    )
    demo_rows = build_demo_results(problem_ids)
    database.add_all(demo_rows)
    database.commit()
    return len(demo_rows)


def reset_results(seed_demo: bool = False) -> None:
    """Reset saved evaluation results and optionally seed a clean demo set."""
    seed_database()

    with SessionLocal() as database:
        problem_count = database.scalar(select(func.count()).select_from(Problem)) or 0
        deleted_rows = clear_evaluation_results(database)
        print("Deleted evaluation results: {0}".format(deleted_rows))
        print("Problems preserved: {0}".format(problem_count))

        if seed_demo:
            inserted_rows = seed_demo_results(database)
            print("Seeded demo results: {0}".format(inserted_rows))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clear saved evaluation history for demos."
    )
    parser.add_argument(
        "--seed-demo",
        action="store_true",
        help="Seed a small clean set of demo results after clearing old rows.",
    )
    args = parser.parse_args()
    reset_results(seed_demo=args.seed_demo)


if __name__ == "__main__":
    main()
