import json
import re
from pathlib import Path
from typing import Optional

from sqlalchemy import inspect, select, text

from app.database import Base, SessionLocal, engine
from app.models import Problem
from app.problem_loader import (
    LEGACY_SCHEMA,
    detect_problem_schema,
    load_problem_definitions,
)


NEW_PROBLEM_COLUMNS = {
    "problem_key": "VARCHAR",
    "problem_type": "VARCHAR",
    "raw_definition_json": "TEXT",
}

NEW_EVALUATION_RESULT_COLUMNS = {
    "score_earned": "FLOAT",
    "score_possible": "FLOAT",
    "score_percentage": "FLOAT",
    "competition_run_id": "VARCHAR",
    "quality_status": "VARCHAR",
    "quality_score": "FLOAT",
    "competition_score": "FLOAT",
    "quality_breakdown_json": "TEXT",
    "quality_reason": "TEXT",
    "ai_analysis_status": "VARCHAR",
    "ai_analysis_score": "FLOAT",
    "ai_analysis_json": "TEXT",
    "ai_analysis_reviewer": "TEXT",
    "ai_analysis_prompt_version": "VARCHAR",
    "ai_analysis_created_at": "DATETIME",
    "ai_analysis_error": "TEXT",
    "comparison_json": "TEXT",
}

NEW_COMPETITION_RUN_COLUMNS = {
    "model_names_json": "TEXT",
    "completed_at": "DATETIME",
}


def _add_missing_problem_columns(database_engine) -> None:
    """Add the JSON index columns to databases created before Phase 9."""
    existing_columns = {
        column["name"]
        for column in inspect(database_engine).get_columns("problems")
    }

    with database_engine.begin() as connection:
        for column_name, column_type in NEW_PROBLEM_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE problems ADD COLUMN "
                        f"{column_name} {column_type}"
                    )
                )


def _add_missing_evaluation_result_columns(database_engine) -> None:
    existing_columns = {
        column["name"]
        for column in inspect(database_engine).get_columns("evaluation_results")
    }

    with database_engine.begin() as connection:
        for column_name, column_type in NEW_EVALUATION_RESULT_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE evaluation_results ADD COLUMN "
                        f"{column_name} {column_type}"
                    )
                )


def _add_missing_competition_run_columns(database_engine) -> None:
    inspector = inspect(database_engine)
    if "competition_runs" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("competition_runs")
    }

    with database_engine.begin() as connection:
        for column_name, column_type in NEW_COMPETITION_RUN_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE competition_runs ADD COLUMN "
                        f"{column_name} {column_type}"
                    )
                )


def _required_function(definition: dict) -> str:
    if definition.get("type") == "css_static_region":
        return ""

    signature = definition.get("function_signature", "")
    match = re.search(r"def\s+([A-Za-z_][A-Za-z0-9_]*)", signature)
    return match.group(1) if match else ""


def _upsert_legacy_problem(problem: Problem, definition: dict) -> None:
    files = definition["files"]
    editable_file = next(
        (file_definition for file_definition in files if file_definition["editable"]),
        files[0],
    )
    metadata = definition["metadata"]
    tags = metadata.get("tags", [])

    problem.problem_key = definition["id"]
    problem.problem_type = definition["type"]
    problem.title = definition["title"]
    problem.category = (
        str(tags[0]).replace("-", " ").title()
        if tags
        else definition["type"].title()
    )
    problem.difficulty = str(metadata.get("difficulty", "Unknown")).title()
    problem.language = definition["language"].title()
    problem.description = definition["description"]
    problem.starter_code = editable_file["starter_content"]
    problem.required_file = editable_file["filename"]
    problem.required_function = _required_function(definition)
    problem.raw_definition_json = json.dumps(definition, ensure_ascii=False)


def _upsert_universal_problem(problem: Problem, definition: dict) -> None:
    files = definition["files"]
    editable_file = next(
        file_definition
        for file_definition in files
        if file_definition["role"] == "editable"
    )
    metadata = definition.get("metadata", {})

    problem.problem_key = definition["id"]
    problem.problem_type = definition["evaluatorType"]
    problem.title = definition["title"]
    problem.category = definition["assignmentType"]
    problem.difficulty = str(metadata.get("difficulty", "Unknown"))
    problem.language = definition["language"]
    problem.description = definition["description"]
    problem.starter_code = editable_file["content"] or ""
    problem.required_file = editable_file["path"]
    problem.required_function = ""
    problem.raw_definition_json = json.dumps(definition, ensure_ascii=False)


def upsert_problem_definition(database, definition: dict) -> Problem:
    """Insert or update one SQLite problem index row from JSON data."""
    problem = database.scalar(
        select(Problem).where(Problem.problem_key == definition["id"])
    )

    if problem is None:
        problem = database.scalar(
            select(Problem).where(Problem.title == definition["title"])
        )

    if problem is None:
        problem = Problem()
        database.add(problem)

    schema = detect_problem_schema(definition)

    if schema == LEGACY_SCHEMA:
        _upsert_legacy_problem(problem, definition)
    else:
        _upsert_universal_problem(problem, definition)

    return problem


def seed_database(
    database_engine=engine,
    session_factory=SessionLocal,
    problem_bank_path: Optional[Path] = None,
) -> None:
    """Create tables and upsert JSON problem definitions into SQLite."""
    Base.metadata.create_all(bind=database_engine)
    _add_missing_problem_columns(database_engine)
    _add_missing_evaluation_result_columns(database_engine)
    _add_missing_competition_run_columns(database_engine)
    definitions = load_problem_definitions(problem_bank_path)
    definitions.sort(key=lambda definition: definition["id"] != "two_sum")

    with session_factory() as database:
        for definition in definitions:
            upsert_problem_definition(database, definition)

        database.commit()
