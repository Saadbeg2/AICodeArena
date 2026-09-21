from collections.abc import Generator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import asynccontextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.database import SessionLocal
from app.browser_qunit_evaluator import (
    evaluate_browser_qunit_problem,
    playwright_runtime_available,
)
from app.ai_analysis import (
    AI_ANALYSIS_DISABLED_MESSAGE,
    build_ai_analysis_input,
    determine_ai_analysis_review_mode,
    generate_ai_analysis,
    is_ai_analysis_eligible_result,
    is_functionally_perfect_result,
    validate_ai_analysis_payload,
)
from app.css_static_checker import evaluate_css_static_region
from app.judge0_client import run_python_code
from app.model_adapters import (
    generate_solution,
    get_active_model_catalog,
    get_competition_stale_threshold_seconds,
    get_default_competition_models,
    get_provider_timeout_seconds,
)
from app.models import EvaluationResult, EvaluationTestResult, Problem
from app.models import CompetitionRun
from app.node_jest_pug_evaluator import (
    NODE_EVALUATOR_TYPE,
    evaluate_node_jest_pug_problem,
    node_runtime_available,
)
from app.problem_loader import (
    DEFAULT_PROBLEM_BANK,
    UNIVERSAL_SCHEMA,
    detect_problem_schema,
    load_problem_definition,
    validate_problem_definition,
)
from app.prompt_builder import build_problem_prompt
from app.reference_comparison import (
    build_submitted_editable_files,
    compare_submitted_files_to_reference,
)
from app.seed import seed_database, upsert_problem_definition
from app.submission_validator import (
    validate_css_declaration_submission,
    validate_universal_submission,
    validate_raw_code_submission,
)
from app.test_harness import (
    SAMPLE_TWO_SUM_SOLUTION,
    build_problem_test_harness,
    build_python_test_harness,
)

load_dotenv()


PROBLEM_BANK_PATH = DEFAULT_PROBLEM_BANK
SAFE_PROBLEM_KEY_PATTERN = re.compile(r"^[a-z0-9_-]+$")
DEFAULT_COMPETITION_RUN_STATUS = "completed"
COMPETITION_RUN_STATUS_WITH_ERRORS = "completed_with_errors"
COMPETITION_RUN_STATUS_RUNNING = "running"
COMPETITION_RUN_STATUS_INTERRUPTED = "Interrupted"
COMPETITION_TIMEOUT_STATUSES = {"Timed Out", "Time Limit Exceeded"}
COMPETITION_RECONCILIATION_LOCK = threading.Lock()
QUALITY_GRADING_DISABLED_REASON = "Deterministic quality grading is disabled."


class ProblemResponse(BaseModel):
    id: int
    title: str
    category: str
    difficulty: str
    language: str
    description: str
    starter_code: str
    required_file: str
    required_function: str

    model_config = ConfigDict(from_attributes=True)


class ModelInfoResponse(BaseModel):
    id: str
    display_name: str
    provider: str
    model_creator: str
    api_provider: str
    description: str
    provider_type: str


class PromptResponse(BaseModel):
    problem_id: int
    prompt: str


class HarnessResponse(BaseModel):
    problem_id: int
    harness: str


class ExecutionResultResponse(BaseModel):
    status: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    compile_output: Optional[str] = None
    time: Optional[str] = None
    memory: Optional[int] = None
    passed_tests: Optional[int] = None
    failed_tests: Optional[int] = None
    total_tests: Optional[int] = None
    score_earned: Optional[float] = None
    score_possible: Optional[float] = None
    score_percentage: Optional[float] = None
    quality_status: Optional[str] = None
    quality_score: Optional[float] = None
    competition_score: Optional[float] = None
    quality_breakdown: Optional[dict] = None
    quality_reason: Optional[str] = None
    ai_analysis_status: Optional[str] = None
    ai_analysis_score: Optional[float] = None
    ai_analysis_available: Optional[bool] = None
    ai_analysis_completed: Optional[bool] = None
    test_results: Optional[list[dict]] = None
    duration_ms: Optional[int] = None


class JudgeResultResponse(ExecutionResultResponse):
    result_id: int


class ModelRunRequest(BaseModel):
    model_name: str = "gemini-flash-latest"


class ModelRunResponse(BaseModel):
    problem_id: int
    model_name: str
    raw_response: str
    cleaned_code: Optional[str] = None
    execution_result: ExecutionResultResponse
    result_id: int


class CompetitionRequest(BaseModel):
    model_names: Optional[list[str]] = None


class CompetitionResultResponse(BaseModel):
    rank: Optional[int] = None
    model_name: str
    competition_run_id: Optional[str] = None
    status: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    time: Optional[str] = None
    passed_tests: Optional[int] = None
    failed_tests: Optional[int] = None
    total_tests: Optional[int] = None
    score_earned: Optional[float] = None
    score_possible: Optional[float] = None
    score_percentage: Optional[float] = None
    quality_status: Optional[str] = None
    quality_score: Optional[float] = None
    competition_score: Optional[float] = None
    quality_breakdown: Optional[dict] = None
    quality_reason: Optional[str] = None
    ai_analysis_status: Optional[str] = None
    ai_analysis_score: Optional[float] = None
    ai_analysis_available: Optional[bool] = None
    ai_analysis_completed: Optional[bool] = None
    test_results: Optional[list[dict]] = None
    result_id: int


class CompetitionResponse(BaseModel):
    problem_id: int
    competition_run_id: Optional[str] = None
    status: str
    model_names: list[str] = []
    expected_model_count: int
    completed_model_count: int
    total_models: int
    results: list[CompetitionResultResponse]


class LeaderboardEntryResponse(BaseModel):
    rank: int
    model_name: str
    result_id: int
    competition_run_id: Optional[str] = None
    total_runs: int
    accepted_runs: int
    failed_runs: int
    timeout_runs: int
    status: str
    latest_status: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    time: Optional[str] = None
    passed_tests: Optional[int] = None
    failed_tests: Optional[int] = None
    total_tests: Optional[int] = None
    score_earned: Optional[float] = None
    score_possible: Optional[float] = None
    score_percentage: Optional[float] = None
    quality_status: Optional[str] = None
    quality_score: Optional[float] = None
    competition_score: Optional[float] = None
    quality_breakdown: Optional[dict] = None
    quality_reason: Optional[str] = None
    ai_analysis_status: Optional[str] = None
    ai_analysis_score: Optional[float] = None
    ai_analysis_available: Optional[bool] = None
    ai_analysis_completed: Optional[bool] = None
    test_results: Optional[list[dict]] = None
    best_time: Optional[str] = None
    average_time: Optional[str] = None


class LeaderboardResponse(BaseModel):
    problem_id: Optional[int] = None
    leaderboard: list[LeaderboardEntryResponse]


class AdminProblemSummaryResponse(BaseModel):
    id: int
    problem_key: str
    title: str
    type: str
    language: str
    file_count: int


class EvaluationResultResponse(BaseModel):
    id: int
    problem_id: int
    model_name: str
    mode: str
    competition_run_id: Optional[str] = None
    status: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    compile_output: Optional[str] = None
    time: Optional[str] = None
    memory: Optional[int] = None
    passed_tests: Optional[int] = None
    failed_tests: Optional[int] = None
    total_tests: Optional[int] = None
    score_earned: Optional[float] = None
    score_possible: Optional[float] = None
    score_percentage: Optional[float] = None
    quality_status: Optional[str] = None
    quality_score: Optional[float] = None
    competition_score: Optional[float] = None
    quality_breakdown: Optional[dict] = None
    quality_reason: Optional[str] = None
    ai_analysis_status: Optional[str] = None
    ai_analysis_score: Optional[float] = None
    ai_analysis_available: Optional[bool] = None
    ai_analysis_completed: Optional[bool] = None
    test_results: Optional[list[dict]] = None
    created_at: datetime
    model_config = ConfigDict()


class AIAnalysisResponse(BaseModel):
    result_id: int
    problem_id: int
    analysis_status: str
    analysis_score: Optional[float] = None
    review_mode: Optional[str] = None
    analysis: Optional[dict] = None
    reviewer: Optional[dict] = None
    created_at: Optional[datetime] = None
    cached: bool


class ComparisonFileResponse(BaseModel):
    path: str
    language: Optional[str] = None
    exact_match: bool
    normalized_match: bool
    added_line_count: int
    removed_line_count: int
    changed_line_count: int
    unified_diff_available: bool = False
    unified_diff_line_count: int = 0


class ComparisonDataResponse(BaseModel):
    reference_available: bool
    reference_source: Optional[str] = None
    compared_file_paths: list[str]
    missing_submitted_files: list[str]
    unexpected_submitted_files: list[str]
    files: list[ComparisonFileResponse]
    overall_exact_match: bool
    overall_normalized_match: bool


class ComparisonFileContentResponse(BaseModel):
    path: str
    language: Optional[str] = None
    content: str


class ResultComparisonResponse(BaseModel):
    result_id: int
    problem_id: int
    model_name: str
    status: str
    score_earned: Optional[float] = None
    score_possible: Optional[float] = None
    score_percentage: Optional[float] = None
    quality_status: Optional[str] = None
    quality_score: Optional[float] = None
    competition_score: Optional[float] = None
    quality_breakdown: Optional[dict] = None
    quality_reason: Optional[str] = None
    created_at: datetime
    comparison_available: bool
    comparison: Optional[ComparisonDataResponse] = None
    reference_files: list[ComparisonFileContentResponse] = []
    submitted_files: list[ComparisonFileContentResponse] = []
    message: Optional[str] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_database()
    with SessionLocal() as database:
        reconcile_stale_competition_runs(database)
    yield


app = FastAPI(
    title="AICodeArena API",
    description="Backend foundation for evaluating AI-generated code.",
    version="0.1.0",
    lifespan=lifespan,
)

frontend_origins = os.getenv(
    "FRONTEND_ORIGINS",
    "http://127.0.0.1:5173,http://localhost:5173",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in frontend_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_database() -> Generator[Session, None, None]:
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()


def get_execution_mode() -> str:
    return (
        "mock"
        if os.getenv("JUDGE0_MODE", "").strip().lower() == "mock"
        else "live"
    )


def get_model_execution_timeout_seconds() -> float:
    return float(get_provider_timeout_seconds())


def is_universal_problem(problem: Problem) -> bool:
    if not problem.raw_definition_json:
        return False

    try:
        definition = json.loads(problem.raw_definition_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False

    return detect_problem_schema(definition) == UNIVERSAL_SCHEMA


def get_universal_definition(problem: Problem) -> Optional[dict]:
    if not problem.raw_definition_json:
        return None

    try:
        definition = json.loads(problem.raw_definition_json)
        if detect_problem_schema(definition) == UNIVERSAL_SCHEMA:
            return definition
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    return None


def is_browser_qunit_problem(definition: dict) -> bool:
    return str(definition.get("evaluatorType", "")).startswith("browser_qunit_")


def evaluate_universal_problem(
    definition: dict,
    submitted_code: str,
) -> dict:
    evaluator_type = definition.get("evaluatorType")

    if evaluator_type == NODE_EVALUATOR_TYPE:
        available, reason = node_runtime_available()
        if not available:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Node evaluation is not available. "
                    f"{reason or 'Install Node.js and npm.'}"
                ),
            )

        return evaluate_node_jest_pug_problem(
            definition,
            submitted_code,
        ).to_execution_result()

    if is_browser_qunit_problem(definition):
        available, reason = playwright_runtime_available()
        if not available:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Browser evaluation is not available. "
                    f"{reason or 'Install Playwright and Chromium.'}"
                ),
            )

        return evaluate_browser_qunit_problem(
            definition,
            submitted_code,
        ).to_execution_result()

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported universal evaluator type: {evaluator_type}",
    )


def _serialize_test_result_row(test_result: EvaluationTestResult) -> dict:
    details = {}
    if test_result.details_json:
        try:
            details = json.loads(test_result.details_json)
        except (json.JSONDecodeError, TypeError):
            details = {}

    return {
        "test_id": test_result.test_id,
        "name": test_result.test_name,
        "status": test_result.status,
        "points_earned": test_result.points_earned,
        "points_possible": test_result.points_possible,
        "message": test_result.message,
        "assertions": details.get("assertions", []),
        "console_errors": details.get("console_errors", []),
        "page_errors": details.get("page_errors", []),
        "diagnostics": details.get("diagnostics", {}),
        "duration_ms": test_result.duration_ms,
    }


def _parse_json_field(raw_value: Optional[str], fallback: Any) -> Any:
    if not raw_value:
        return fallback
    try:
        return json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _scored_test_definitions(problem: Optional[Problem]) -> Optional[list[dict]]:
    definition = get_universal_definition(problem) if problem is not None else None
    if not definition:
        return None

    tests = definition.get("tests")
    if not isinstance(tests, list):
        return None

    return [
        test_definition
        for test_definition in tests
        if float(test_definition.get("points", 0.0) or 0.0) > 0.0
    ]


def _normalize_test_results(
    problem: Optional[Problem],
    test_results: list[dict],
) -> list[dict]:
    scored_definitions = _scored_test_definitions(problem)
    if not scored_definitions:
        return test_results

    scored_test_order = []
    scored_test_ids = set()
    for test_definition in scored_definitions:
        test_id = str(test_definition.get("id", "")).strip()
        if not test_id:
            continue
        scored_test_order.append(test_id)
        scored_test_ids.add(test_id)

    latest_by_test_id = {}
    fallback_results = []

    for test_result in test_results:
        points_possible = float(test_result.get("points_possible", 0.0) or 0.0)
        if points_possible <= 0.0:
            continue

        test_id = str(test_result.get("test_id", "")).strip()
        if test_id in scored_test_ids:
            latest_by_test_id[test_id] = test_result
        elif not scored_test_ids:
            fallback_results.append(test_result)

    normalized_results = [
        latest_by_test_id[test_id]
        for test_id in scored_test_order
        if test_id in latest_by_test_id
    ]

    return normalized_results or fallback_results


def summarize_test_results(test_results: Optional[list[dict]]) -> dict:
    if not test_results:
        return {
            "passed_tests": None,
            "failed_tests": None,
            "total_tests": None,
        }

    passed_tests = 0
    failed_tests = 0

    for test_result in test_results:
        if test_result.get("status") == "passed":
            passed_tests += 1
        else:
            failed_tests += 1

    return {
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "total_tests": len(test_results),
    }


def summarize_problem_test_results(
    problem: Optional[Problem],
    test_results: Optional[list[dict]],
) -> dict:
    normalized_results = _normalize_test_results(problem, test_results or [])
    summary = summarize_test_results(normalized_results)
    scored_definitions = _scored_test_definitions(problem)

    if scored_definitions is not None and normalized_results:
        total_scored_tests = len(scored_definitions)
        summary["total_tests"] = total_scored_tests
        summary["failed_tests"] = total_scored_tests - (summary["passed_tests"] or 0)

    return {
        **summary,
        "test_results": normalized_results,
    }


def enrich_execution_result(result: dict) -> dict:
    enriched_result = dict(result)
    enriched_result.update(
        summarize_test_results(enriched_result.get("test_results"))
    )
    return enriched_result


def apply_problem_test_summary(problem: Optional[Problem], result: dict) -> dict:
    enriched_result = dict(result)
    summary = summarize_problem_test_results(
        problem,
        enriched_result.get("test_results"),
    )
    enriched_result["passed_tests"] = summary["passed_tests"]
    enriched_result["failed_tests"] = summary["failed_tests"]
    enriched_result["total_tests"] = summary["total_tests"]
    enriched_result["test_results"] = summary["test_results"]
    return enriched_result


def apply_disabled_quality_state(result: dict) -> dict:
    enriched_result = dict(result)
    enriched_result["quality_status"] = "disabled"
    enriched_result["quality_score"] = None
    enriched_result["competition_score"] = None
    enriched_result["quality_breakdown"] = None
    enriched_result["quality_reason"] = QUALITY_GRADING_DISABLED_REASON
    return enriched_result


def _extract_candidate_files_from_comparison(saved_result: EvaluationResult) -> list[dict]:
    comparison_payload = _parse_json_field(saved_result.comparison_json, None)
    if not isinstance(comparison_payload, dict):
        return []

    submitted_files = comparison_payload.get("submitted_files", [])
    if not isinstance(submitted_files, list):
        return []

    return [
        {
            "path": file_definition.get("path", ""),
            "language": file_definition.get("language"),
            "content": file_definition.get("content", ""),
        }
        for file_definition in submitted_files
        if file_definition.get("path") and file_definition.get("content") is not None
    ]


def _result_supports_ai_analysis(
    saved_result: EvaluationResult,
    problem: Optional[Problem],
) -> bool:
    serialized_result = {
        "status": saved_result.status,
        "score_earned": saved_result.score_earned,
        "score_possible": saved_result.score_possible,
        "score_percentage": saved_result.score_percentage,
    }
    if not is_ai_analysis_eligible_result(serialized_result):
        return False

    if problem is None:
        return False

    return bool(
        _extract_candidate_files_from_comparison(saved_result)
        and _extract_reference_files(problem)
    )


def _serialize_ai_analysis_state(
    saved_result: EvaluationResult,
    problem: Optional[Problem],
) -> dict:
    ai_analysis_status = saved_result.ai_analysis_status or "not_requested"
    return {
        "ai_analysis_status": ai_analysis_status,
        "ai_analysis_score": saved_result.ai_analysis_score,
        "ai_analysis_available": _result_supports_ai_analysis(saved_result, problem),
        "ai_analysis_completed": (
            ai_analysis_status == "completed" and bool(saved_result.ai_analysis_json)
        ),
    }


def _sanitize_comparison_data(comparison_data: dict) -> dict:
    sanitized_files = []

    for file_result in comparison_data.get("files", []) or []:
        unified_diff = file_result.get("unified_diff", []) or []
        sanitized_files.append(
            {
                "path": file_result.get("path", ""),
                "language": file_result.get("language"),
                "exact_match": bool(file_result.get("exact_match")),
                "normalized_match": bool(file_result.get("normalized_match")),
                "added_line_count": int(file_result.get("added_line_count", 0) or 0),
                "removed_line_count": int(
                    file_result.get("removed_line_count", 0) or 0
                ),
                "changed_line_count": int(
                    file_result.get("changed_line_count", 0) or 0
                ),
                "unified_diff_available": bool(unified_diff),
                "unified_diff_line_count": len(unified_diff),
            }
        )

    return {
        "reference_available": bool(comparison_data.get("reference_available")),
        "reference_source": comparison_data.get("reference_source"),
        "compared_file_paths": list(comparison_data.get("compared_file_paths", [])),
        "missing_submitted_files": list(
            comparison_data.get("missing_submitted_files", [])
        ),
        "unexpected_submitted_files": list(
            comparison_data.get("unexpected_submitted_files", [])
        ),
        "files": sanitized_files,
        "overall_exact_match": bool(comparison_data.get("overall_exact_match")),
        "overall_normalized_match": bool(
            comparison_data.get("overall_normalized_match")
        ),
    }


def _extract_reference_files(problem: Problem) -> list[dict]:
    definition = get_universal_definition(problem)
    if not definition:
        return []

    reference_solution = definition.get("referenceSolution") or {}
    reference_files = reference_solution.get("files", []) or []
    return [
        {
            "path": file_definition.get("path", ""),
            "language": file_definition.get("language"),
            "content": file_definition.get("content", ""),
        }
        for file_definition in reference_files
        if file_definition.get("path") and file_definition.get("content") is not None
    ]


def build_result_comparison_response(
    saved_result: EvaluationResult,
    problem: Problem,
) -> dict:
    if not saved_result.comparison_json:
        raise HTTPException(
            status_code=404,
            detail="Comparison data not found for this evaluation result.",
        )

    try:
        parsed_comparison = json.loads(saved_result.comparison_json)
    except (json.JSONDecodeError, TypeError):
        return {
            "result_id": saved_result.id,
            "problem_id": saved_result.problem_id,
            "model_name": saved_result.model_name,
            "status": saved_result.status,
            "score_earned": saved_result.score_earned,
            "score_possible": saved_result.score_possible,
            "score_percentage": saved_result.score_percentage,
            "quality_status": saved_result.quality_status,
            "quality_score": saved_result.quality_score,
            "competition_score": saved_result.competition_score,
            "quality_breakdown": None,
            "quality_reason": saved_result.quality_reason,
            "created_at": saved_result.created_at,
            "comparison_available": False,
            "comparison": None,
            "reference_files": [],
            "submitted_files": [],
            "message": "Stored comparison data is malformed and could not be parsed safely.",
        }

    submitted_files = list(parsed_comparison.get("submitted_files", []) or [])

    return {
        "result_id": saved_result.id,
        "problem_id": saved_result.problem_id,
        "model_name": saved_result.model_name,
        "status": saved_result.status,
        "score_earned": saved_result.score_earned,
        "score_possible": saved_result.score_possible,
        "score_percentage": saved_result.score_percentage,
        "quality_status": saved_result.quality_status,
        "quality_score": saved_result.quality_score,
        "competition_score": saved_result.competition_score,
        "quality_breakdown": _parse_json_field(saved_result.quality_breakdown_json, None),
        "quality_reason": saved_result.quality_reason,
        "created_at": saved_result.created_at,
        "comparison_available": True,
        "comparison": _sanitize_comparison_data(parsed_comparison),
        "reference_files": _extract_reference_files(problem),
        "submitted_files": submitted_files,
        "message": None,
    }


def build_ai_analysis_response(
    saved_result: EvaluationResult,
    cached: bool,
) -> dict:
    raw_payload = _parse_json_field(saved_result.ai_analysis_json, None)
    analysis_payload = raw_payload
    reviewer = None
    review_mode = None

    if isinstance(analysis_payload, dict):
        if analysis_payload.get("format") == "plain_text":
            review_text = str(analysis_payload.get("review_text", "")).strip()
            if not review_text:
                analysis_payload = None
            else:
                review_mode = analysis_payload.get("review_mode")
                analysis_payload = {
                    "format": "plain_text",
                    "review_mode": review_mode,
                    "review_text": review_text,
                }
                raw_reviewer = raw_payload.get("reviewer") if isinstance(raw_payload, dict) else None
                if isinstance(raw_reviewer, dict):
                    reviewer = raw_reviewer
        else:
            try:
                analysis_payload = validate_ai_analysis_payload(analysis_payload)
            except ValueError:
                analysis_payload = None
            if isinstance(analysis_payload, dict):
                review_mode = analysis_payload.get("review_mode")
                raw_reviewer = analysis_payload.get("reviewer")
                if isinstance(raw_reviewer, dict):
                    reviewer = raw_reviewer

    return {
        "result_id": saved_result.id,
        "problem_id": saved_result.problem_id,
        "analysis_status": saved_result.ai_analysis_status or "not_requested",
        "analysis_score": saved_result.ai_analysis_score,
        "review_mode": review_mode,
        "analysis": analysis_payload,
        "reviewer": reviewer,
        "created_at": saved_result.ai_analysis_created_at,
        "cached": cached,
    }


def _persist_ai_analysis_failure(
    database: Session,
    saved_result: EvaluationResult,
    error_message: str,
) -> None:
    saved_result.ai_analysis_status = "failed"
    saved_result.ai_analysis_score = None
    saved_result.ai_analysis_json = None
    saved_result.ai_analysis_reviewer = None
    saved_result.ai_analysis_prompt_version = None
    saved_result.ai_analysis_created_at = None
    saved_result.ai_analysis_error = error_message
    database.commit()
    database.refresh(saved_result)


def _persist_completed_ai_analysis(
    database: Session,
    saved_result: EvaluationResult,
    analysis_payload: dict,
) -> EvaluationResult:
    reviewer = analysis_payload.get("reviewer", {})
    saved_result.ai_analysis_status = "completed"
    saved_result.ai_analysis_score = analysis_payload.get("score")
    saved_result.ai_analysis_json = json.dumps(analysis_payload, ensure_ascii=False)
    saved_result.ai_analysis_reviewer = reviewer.get("used_model")
    saved_result.ai_analysis_prompt_version = reviewer.get("prompt_version")
    saved_result.ai_analysis_created_at = datetime.utcnow()
    saved_result.ai_analysis_error = None
    database.commit()
    database.refresh(saved_result)
    return saved_result


def serialize_evaluation_result(
    saved_result: EvaluationResult,
    problem: Optional[Problem] = None,
) -> dict:
    raw_test_results = [
        _serialize_test_result_row(test_result)
        for test_result in saved_result.test_results
    ]
    summary = summarize_problem_test_results(problem, raw_test_results)
    quality_breakdown = _parse_json_field(saved_result.quality_breakdown_json, None)
    quality_status = saved_result.quality_status or "unavailable"
    ai_analysis_state = _serialize_ai_analysis_state(saved_result, problem)

    return {
        "id": saved_result.id,
        "problem_id": saved_result.problem_id,
        "model_name": saved_result.model_name,
        "mode": saved_result.mode,
        "competition_run_id": saved_result.competition_run_id,
        "status": saved_result.status,
        "stdout": saved_result.stdout,
        "stderr": saved_result.stderr,
        "compile_output": saved_result.compile_output,
        "time": saved_result.time,
        "memory": saved_result.memory,
        "passed_tests": summary["passed_tests"],
        "failed_tests": summary["failed_tests"],
        "total_tests": summary["total_tests"],
        "score_earned": saved_result.score_earned,
        "score_possible": saved_result.score_possible,
        "score_percentage": saved_result.score_percentage,
        "quality_status": quality_status,
        "quality_score": saved_result.quality_score,
        "competition_score": saved_result.competition_score,
        "quality_breakdown": quality_breakdown,
        "quality_reason": saved_result.quality_reason,
        **ai_analysis_state,
        "test_results": summary["test_results"],
        "created_at": saved_result.created_at,
    }


def save_evaluation_result(
    database: Session,
    problem_id: int,
    model_name: str,
    result: dict,
    comparison: Optional[dict] = None,
    competition_run_id: Optional[str] = None,
) -> EvaluationResult:
    saved_result = EvaluationResult(
        problem_id=problem_id,
        model_name=model_name,
        mode=get_execution_mode(),
        competition_run_id=competition_run_id,
        status=result["status"],
        stdout=result.get("stdout"),
        stderr=result.get("stderr"),
        compile_output=result.get("compile_output"),
        time=result.get("time"),
        memory=result.get("memory"),
        score_earned=result.get("score_earned"),
        score_possible=result.get("score_possible"),
        score_percentage=result.get("score_percentage"),
        quality_status=result.get("quality_status"),
        quality_score=result.get("quality_score"),
        competition_score=result.get("competition_score"),
        quality_breakdown_json=(
            json.dumps(result.get("quality_breakdown"), ensure_ascii=False)
            if result.get("quality_breakdown") is not None
            else None
        ),
        quality_reason=result.get("quality_reason"),
        ai_analysis_status=result.get("ai_analysis_status"),
        ai_analysis_score=result.get("ai_analysis_score"),
        comparison_json=(
            json.dumps(comparison, ensure_ascii=False)
            if comparison is not None
            else None
        ),
    )

    for test_result in result.get("test_results", []) or []:
        details = {
            "assertions": test_result.get("assertions", []),
            "console_errors": test_result.get("console_errors", []),
            "page_errors": test_result.get("page_errors", []),
            "diagnostics": test_result.get("diagnostics", {}),
        }
        saved_result.test_results.append(
            EvaluationTestResult(
                test_id=test_result.get("test_id", ""),
                test_name=test_result.get("name", ""),
                status=test_result.get("status", ""),
                points_earned=float(test_result.get("points_earned", 0.0) or 0.0),
                points_possible=float(test_result.get("points_possible", 0.0) or 0.0),
                message=test_result.get("message"),
                details_json=json.dumps(details, ensure_ascii=False),
                duration_ms=test_result.get("duration_ms"),
            )
        )

    database.add(saved_result)
    database.flush()
    saved_result_id = saved_result.id
    database.commit()
    saved_result = database.scalar(
        select(EvaluationResult)
        .options(selectinload(EvaluationResult.test_results))
        .where(EvaluationResult.id == saved_result_id)
    )
    return saved_result


def save_competition_run(
    database: Session,
    problem_id: int,
    competition_run_id: str,
    total_models: int,
    status: str,
    model_names: list[str],
) -> CompetitionRun:
    competition_run = CompetitionRun(
        id=competition_run_id,
        problem_id=problem_id,
        total_models=total_models,
        status=status,
        model_names_json=json.dumps(model_names, ensure_ascii=False),
    )
    database.add(competition_run)
    database.commit()
    database.refresh(competition_run)
    return competition_run


def update_competition_run_status(
    database: Session,
    competition_run_id: str,
    status: str,
) -> None:
    competition_run = database.get(CompetitionRun, competition_run_id)
    if competition_run is None:
        return

    competition_run.status = status
    competition_run.completed_at = (
        None
        if status == COMPETITION_RUN_STATUS_RUNNING
        else datetime.utcnow()
    )
    try:
        database.commit()
    except Exception:
        try:
            database.rollback()
        except Exception:
            pass


def _parse_competition_run_model_names(
    competition_run: Optional[CompetitionRun],
) -> list[str]:
    if competition_run is None or not competition_run.model_names_json:
        return []

    try:
        model_names = json.loads(competition_run.model_names_json)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(model_names, list):
        return []

    return [str(model_name) for model_name in model_names]


def _determine_competition_run_status(results: list[dict]) -> str:
    if any(result.get("status") != "Accepted" for result in results):
        return COMPETITION_RUN_STATUS_WITH_ERRORS
    return DEFAULT_COMPETITION_RUN_STATUS


def build_timeout_execution_result(timeout_seconds: float) -> dict:
    return enrich_execution_result(
        {
            "status": "Timed Out",
            "stdout": None,
            "stderr": "The model exceeded the allowed execution time.",
            "compile_output": None,
            "time": f"{timeout_seconds:.3f}".rstrip("0").rstrip("."),
            "memory": None,
        }
    )


def build_interrupted_execution_result() -> dict:
    return enrich_execution_result(
        {
            "status": COMPETITION_RUN_STATUS_INTERRUPTED,
            "stdout": None,
            "stderr": (
                "This model did not finish because the competition worker was interrupted "
                "before it could persist a terminal result."
            ),
            "compile_output": None,
            "time": None,
            "memory": None,
        }
    )


def execute_model_without_persistence(
    problem: Problem,
    model_name: str,
) -> dict:
    problem_prompt = build_problem_prompt(problem)
    generated_solution = generate_solution(problem_prompt, model_name)
    universal_definition = get_universal_definition(problem)
    comparison_result = None

    if universal_definition is not None:
        validation_result = validate_universal_submission(
            problem,
            generated_solution["raw_response"],
        )
    elif problem.problem_type == "css_static_region":
        validation_result = validate_css_declaration_submission(
            generated_solution["raw_response"]
        )
    else:
        validation_result = validate_raw_code_submission(
            generated_solution["raw_response"]
        )

    if not validation_result.is_valid:
        execution_result = enrich_execution_result(
            {
            "status": "FORMAT_ERROR",
            "stdout": None,
            "stderr": validation_result.error_message,
            "compile_output": generated_solution["raw_response"],
            "time": None,
            "memory": None,
            }
        )
        execution_result = apply_disabled_quality_state(execution_result)

        return {
            "problem_id": problem.id,
            "model_name": generated_solution["model_name"],
            "raw_response": generated_solution["raw_response"],
            "cleaned_code": None,
            "execution_result": execution_result,
            "comparison_result": comparison_result,
        }

    if universal_definition is not None:
        submitted_files = build_submitted_editable_files(
            universal_definition,
            validation_result.code,
        )
        comparison_result = compare_submitted_files_to_reference(
            universal_definition,
            submitted_files,
        )
        comparison_result["submitted_files"] = [
            {
                "path": path,
                "language": next(
                    (
                        file_definition.get("language")
                        for file_definition in universal_definition.get("files", [])
                        if file_definition.get("path") == path
                    ),
                    None,
                ),
                "content": content,
            }
            for path, content in submitted_files.items()
        ]
        execution_result = evaluate_universal_problem(
            universal_definition,
            validation_result.code,
        )
    elif problem.problem_type == "css_static_region":
        execution_result = evaluate_css_static_region(problem, validation_result.code)
    else:
        harness = build_problem_test_harness(
            problem,
            validation_result.code,
        )
        execution_result = run_python_code(harness)

    execution_result = enrich_execution_result(execution_result)
    execution_result = apply_problem_test_summary(problem, execution_result)
    execution_result = apply_disabled_quality_state(execution_result)

    return {
        "problem_id": problem.id,
        "model_name": generated_solution["model_name"],
        "raw_response": generated_solution["raw_response"],
        "cleaned_code": validation_result.code,
        "execution_result": execution_result,
        "comparison_result": comparison_result,
    }


def persist_model_execution_result(
    database: Session,
    problem: Problem,
    model_execution: dict,
    competition_run_id: Optional[str] = None,
) -> dict:
    saved_result = save_evaluation_result(
        database,
        problem.id,
        model_execution["model_name"],
        model_execution["execution_result"],
        model_execution.get("comparison_result"),
        competition_run_id=competition_run_id,
    )

    return {
        "problem_id": model_execution["problem_id"],
        "model_name": model_execution["model_name"],
        "raw_response": model_execution["raw_response"],
        "cleaned_code": model_execution.get("cleaned_code"),
        "execution_result": model_execution["execution_result"],
        "result_id": saved_result.id,
        "competition_run_id": saved_result.competition_run_id,
    }


def execute_and_save_model(
    database: Session,
    problem: Problem,
    model_name: str,
    competition_run_id: Optional[str] = None,
) -> dict:
    model_execution = execute_model_without_persistence(problem, model_name)
    return persist_model_execution_result(
        database,
        problem,
        model_execution,
        competition_run_id=competition_run_id,
    )


def _parse_execution_time(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _effective_functional_percentage(result: EvaluationResult) -> float:
    if result.score_percentage is None:
        return -1.0
    return float(result.score_percentage)


def _leaderboard_status_rank(status: str) -> int:
    if status == "Accepted":
        return 3
    if status in COMPETITION_TIMEOUT_STATUSES:
        return 1
    if status in {"Wrong Answer", "Runtime Error", "FORMAT_ERROR", "Adapter Error"}:
        return 2
    return 0


def _leaderboard_sort_key(entry: dict) -> tuple:
    score_percentage = entry.get("score_percentage")
    score_earned = entry.get("score_earned")
    execution_time = _parse_execution_time(entry.get("time"))

    if score_percentage is not None:
        return (
            0,
            -float(score_percentage),
            -float(score_earned) if score_earned is not None else 0.0,
            -_leaderboard_status_rank(entry.get("status", "")),
            execution_time if execution_time is not None else float("inf"),
            -int(entry["result_id"]),
            entry["model_name"],
        )

    return (
        1,
        -_leaderboard_status_rank(entry.get("status", "")),
        execution_time if execution_time is not None else float("inf"),
        -int(entry["accepted_runs"]),
        int(entry["timeout_runs"]),
        int(entry["failed_runs"]),
        -int(entry["result_id"]),
        entry["model_name"],
    )


def _current_run_sort_key(entry: dict) -> tuple:
    score_percentage = entry.get("score_percentage")
    score_earned = entry.get("score_earned")
    execution_time = _parse_execution_time(entry.get("time"))

    return (
        -(1 if score_percentage is not None else 0),
        -float(score_percentage) if score_percentage is not None else 0.0,
        -float(score_earned) if score_earned is not None else 0.0,
        -_leaderboard_status_rank(entry.get("status", "")),
        execution_time if execution_time is not None else float("inf"),
        -int(entry.get("result_id") or entry.get("id") or 0),
        entry.get("model_name", ""),
    )


def _is_better_leaderboard_result(
    candidate: EvaluationResult,
    current_best: EvaluationResult,
) -> bool:
    candidate_functional = _effective_functional_percentage(candidate)
    current_functional = _effective_functional_percentage(current_best)
    if candidate_functional != current_functional:
        return candidate_functional > current_functional

    candidate_earned = float(candidate.score_earned or 0.0)
    current_earned = float(current_best.score_earned or 0.0)
    if candidate_earned != current_earned:
        return candidate_earned > current_earned

    candidate_status_rank = _leaderboard_status_rank(candidate.status)
    current_status_rank = _leaderboard_status_rank(current_best.status)
    if candidate_status_rank != current_status_rank:
        return candidate_status_rank > current_status_rank

    candidate_time = _parse_execution_time(candidate.time)
    current_time = _parse_execution_time(current_best.time)
    if candidate_time != current_time:
        if candidate_time is None:
            return False
        if current_time is None:
            return True
        return candidate_time < current_time

    if candidate.created_at != current_best.created_at:
        return candidate.created_at > current_best.created_at

    return candidate.id > current_best.id


def build_leaderboard(
    results: list[EvaluationResult],
    problem_by_id: Optional[dict[int, Problem]] = None,
) -> list[dict]:
    summaries = {}

    for result in results:
        if result.model_name not in summaries:
            summaries[result.model_name] = {
                "model_name": result.model_name,
                "best_result": result,
                "total_runs": 0,
                "accepted_runs": 0,
                "failed_runs": 0,
                "timeout_runs": 0,
                "accepted_times": [],
            }

        summary = summaries[result.model_name]
        summary["total_runs"] += 1

        if _is_better_leaderboard_result(result, summary["best_result"]):
            summary["best_result"] = result

        if result.status == "Accepted":
            summary["accepted_runs"] += 1

            if result.time is not None:
                try:
                    summary["accepted_times"].append(float(result.time))
                except (TypeError, ValueError):
                    pass
        elif result.status in COMPETITION_TIMEOUT_STATUSES:
            summary["timeout_runs"] += 1
        else:
            summary["failed_runs"] += 1

    leaderboard = []

    for summary in summaries.values():
        best_result = summary.pop("best_result")
        accepted_times = summary.pop("accepted_times")
        best_time = min(accepted_times) if accepted_times else None
        average_time = (
            sum(accepted_times) / len(accepted_times)
            if accepted_times
            else None
        )
        best_problem = (
            problem_by_id.get(best_result.problem_id)
            if problem_by_id is not None
            else None
        )
        serialized_best_result = serialize_evaluation_result(best_result, best_problem)
        test_summary = summarize_problem_test_results(
            best_problem,
            serialized_best_result["test_results"],
        )

        summary["result_id"] = best_result.id
        summary["status"] = best_result.status
        summary["latest_status"] = best_result.status
        summary["stdout"] = best_result.stdout
        summary["stderr"] = best_result.stderr
        summary["time"] = best_result.time
        summary["passed_tests"] = test_summary["passed_tests"]
        summary["failed_tests"] = test_summary["failed_tests"]
        summary["total_tests"] = test_summary["total_tests"]
        summary["score_earned"] = best_result.score_earned
        summary["score_possible"] = best_result.score_possible
        summary["score_percentage"] = best_result.score_percentage
        summary["competition_run_id"] = best_result.competition_run_id
        summary["quality_status"] = best_result.quality_status or "unavailable"
        summary["quality_score"] = best_result.quality_score
        summary["competition_score"] = best_result.competition_score
        summary["quality_breakdown"] = _parse_json_field(
            best_result.quality_breakdown_json,
            None,
        )
        summary["quality_reason"] = best_result.quality_reason
        summary["ai_analysis_status"] = serialized_best_result["ai_analysis_status"]
        summary["ai_analysis_score"] = serialized_best_result["ai_analysis_score"]
        summary["ai_analysis_available"] = serialized_best_result["ai_analysis_available"]
        summary["ai_analysis_completed"] = serialized_best_result["ai_analysis_completed"]
        summary["test_results"] = serialized_best_result["test_results"]
        summary["best_time"] = (
            f"{best_time:.3f}" if best_time is not None else None
        )
        summary["average_time"] = (
            f"{average_time:.3f}" if average_time is not None else None
        )
        leaderboard.append(summary)

    leaderboard.sort(key=_leaderboard_sort_key)

    for rank, entry in enumerate(leaderboard, start=1):
        entry["rank"] = rank

    return leaderboard


def _load_saved_result(
    database: Session,
    result_id: int,
) -> Optional[EvaluationResult]:
    return database.scalar(
        select(EvaluationResult)
        .options(selectinload(EvaluationResult.test_results))
        .where(EvaluationResult.id == result_id)
    )


def build_competition_run_results(
    problem: Problem,
    saved_results: list[EvaluationResult],
) -> list[dict]:
    serialized_results = [
        {
            **serialize_evaluation_result(saved_result, problem),
            "result_id": saved_result.id,
        }
        for saved_result in saved_results
    ]
    serialized_results.sort(key=_current_run_sort_key)

    ranked_results = []
    for rank, result in enumerate(serialized_results, start=1):
        ranked_results.append(
            {
                "rank": rank,
                "model_name": result["model_name"],
                "competition_run_id": result.get("competition_run_id"),
                "status": result["status"],
                "stdout": result.get("stdout"),
                "stderr": result.get("stderr"),
                "time": result.get("time"),
                "passed_tests": result.get("passed_tests"),
                "failed_tests": result.get("failed_tests"),
                "total_tests": result.get("total_tests"),
                "score_earned": result.get("score_earned"),
                "score_possible": result.get("score_possible"),
                "score_percentage": result.get("score_percentage"),
                "quality_status": result.get("quality_status"),
                "quality_score": result.get("quality_score"),
                "competition_score": result.get("competition_score"),
                "quality_breakdown": result.get("quality_breakdown"),
                "quality_reason": result.get("quality_reason"),
                "ai_analysis_status": result.get("ai_analysis_status"),
                "ai_analysis_score": result.get("ai_analysis_score"),
                "ai_analysis_available": result.get("ai_analysis_available"),
                "ai_analysis_completed": result.get("ai_analysis_completed"),
                "test_results": result.get("test_results"),
                "result_id": result["id"],
            }
        )

    return ranked_results


def _competition_run_statement(problem_id: int, competition_run_id: str):
    return (
        select(EvaluationResult)
        .options(selectinload(EvaluationResult.test_results))
        .where(EvaluationResult.problem_id == problem_id)
        .where(EvaluationResult.competition_run_id == competition_run_id)
        .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
    )


def _competition_run_rows_statement(problem_id: int, competition_run_id: str):
    return (
        select(EvaluationResult)
        .where(EvaluationResult.problem_id == problem_id)
        .where(EvaluationResult.competition_run_id == competition_run_id)
        .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
    )


def _build_competition_run_response_status(
    competition_run: Optional[CompetitionRun],
    results: list[EvaluationResult],
) -> str:
    if competition_run is not None:
        return competition_run.status
    return _determine_competition_run_status(
        [
            {"status": result.status}
            for result in results
        ]
    )


def get_competition_run_response(
    problem: Problem,
    competition_run_id: str,
    database: Session,
) -> dict:
    competition_run = database.get(CompetitionRun, competition_run_id)
    saved_results = list(
        database.scalars(
            _competition_run_statement(problem.id, competition_run_id)
        ).all()
    )

    if not saved_results and competition_run is None:
        raise HTTPException(status_code=404, detail="Competition run not found")

    expected_model_count = (
        competition_run.total_models
        if competition_run is not None
        else len(saved_results)
    )
    model_names = _parse_competition_run_model_names(competition_run)
    derived_status = _build_competition_run_response_status(
        competition_run,
        saved_results,
    )

    if (
        competition_run is not None
        and competition_run.status == COMPETITION_RUN_STATUS_RUNNING
        and expected_model_count > 0
        and len(saved_results) >= expected_model_count
    ):
        derived_status = _determine_competition_run_status(
            [{"status": result.status} for result in saved_results]
        )
        update_competition_run_status(
            database,
            competition_run_id,
            derived_status,
        )

    return {
        "problem_id": problem.id,
        "competition_run_id": competition_run_id,
        "status": derived_status,
        "model_names": model_names,
        "expected_model_count": expected_model_count,
        "completed_model_count": len(saved_results),
        "total_models": expected_model_count,
        "results": build_competition_run_results(problem, saved_results),
    }


def _build_problem_execution_copy(problem: Problem) -> Problem:
    execution_problem = Problem(
        title=problem.title,
        category=problem.category,
        difficulty=problem.difficulty,
        language=problem.language,
        description=problem.description,
        starter_code=problem.starter_code,
        required_file=problem.required_file,
        required_function=problem.required_function,
        problem_key=problem.problem_key,
        problem_type=problem.problem_type,
        raw_definition_json=problem.raw_definition_json,
    )
    execution_problem.id = problem.id
    return execution_problem


def _save_competition_adapter_error_result(
    database: Session,
    problem: Problem,
    model_name: str,
    error_message: str,
    competition_run_id: str,
) -> EvaluationResult:
    error_result = enrich_execution_result(
        {
            "status": "Adapter Error",
            "stdout": None,
            "stderr": error_message,
            "compile_output": None,
            "time": None,
            "memory": None,
        }
    )
    error_result = apply_disabled_quality_state(error_result)
    return save_evaluation_result(
        database,
        problem.id,
        model_name,
        error_result,
        None,
        competition_run_id=competition_run_id,
    )


def _save_competition_result_with_retry(
    database: Session,
    save_callable,
    attempts: int = 2,
):
    last_error = None
    for _ in range(attempts):
        try:
            return save_callable()
        except Exception as error:  # pragma: no cover
            last_error = error
            database.rollback()
    if last_error is not None:
        raise last_error


def _competition_run_is_stale(competition_run: CompetitionRun) -> bool:
    if competition_run.status != COMPETITION_RUN_STATUS_RUNNING:
        return False
    age_seconds = (datetime.utcnow() - competition_run.created_at).total_seconds()
    return age_seconds >= get_competition_stale_threshold_seconds()


def _persist_missing_competition_rows(
    database: Session,
    problem: Problem,
    competition_run_id: str,
    expected_model_names: list[str],
    terminal_statuses: dict[str, str],
) -> None:
    saved_results = list(
        database.scalars(
            _competition_run_rows_statement(problem.id, competition_run_id)
        ).all()
    )
    existing_model_names = {result.model_name for result in saved_results}

    for model_name in expected_model_names:
        if model_name in existing_model_names:
            continue

        status = terminal_statuses.get(model_name)
        if status is None:
            continue

        if status == "Adapter Error":
            _save_competition_result_with_retry(
                database,
                lambda model_name=model_name: _save_competition_adapter_error_result(
                    database,
                    problem,
                    model_name,
                    "Competition worker finished without persisting the adapter error result.",
                    competition_run_id,
                ),
            )
            continue

        if status in COMPETITION_TIMEOUT_STATUSES:
            timeout_result = apply_disabled_quality_state(
                build_timeout_execution_result(
                    get_model_execution_timeout_seconds()
                )
            )
            _save_competition_result_with_retry(
                database,
                lambda model_name=model_name, timeout_result=timeout_result: save_evaluation_result(
                    database,
                    problem.id,
                    model_name,
                    timeout_result,
                    None,
                    competition_run_id=competition_run_id,
                ),
            )
            continue


def _reconcile_competition_run_if_needed(
    database: Session,
    competition_run: CompetitionRun,
) -> bool:
    if competition_run.status != COMPETITION_RUN_STATUS_RUNNING:
        return False

    saved_results = list(
        database.scalars(
            _competition_run_rows_statement(
                competition_run.problem_id,
                competition_run.id,
            )
        ).all()
    )
    expected_model_count = competition_run.total_models

    if expected_model_count > 0 and len(saved_results) >= expected_model_count:
        final_status = _determine_competition_run_status(
            [{"status": result.status} for result in saved_results]
        )
        update_competition_run_status(database, competition_run.id, final_status)
        return True

    if not _competition_run_is_stale(competition_run):
        return False

    expected_model_names = _parse_competition_run_model_names(competition_run)
    existing_model_names = {result.model_name for result in saved_results}
    missing_model_names = [
        model_name
        for model_name in expected_model_names
        if model_name not in existing_model_names
    ]
    problem = database.get(Problem, competition_run.problem_id)

    if problem is not None:
        for model_name in missing_model_names:
            existing_result_id = database.scalar(
                select(EvaluationResult.id)
                .where(EvaluationResult.problem_id == competition_run.problem_id)
                .where(EvaluationResult.competition_run_id == competition_run.id)
                .where(EvaluationResult.model_name == model_name)
                .limit(1)
            )
            if existing_result_id is not None:
                continue

            interrupted_result = apply_disabled_quality_state(
                build_interrupted_execution_result()
            )
            _save_competition_result_with_retry(
                database,
                lambda model_name=model_name, interrupted_result=interrupted_result: save_evaluation_result(
                    database,
                    problem.id,
                    model_name,
                    interrupted_result,
                    None,
                    competition_run_id=competition_run.id,
                ),
            )

    final_results = list(
        database.scalars(
            _competition_run_rows_statement(
                competition_run.problem_id,
                competition_run.id,
            )
        ).all()
    )
    final_status = _determine_competition_run_status(
        [{"status": result.status} for result in final_results]
    )
    update_competition_run_status(database, competition_run.id, final_status)
    return True


def reconcile_stale_competition_runs(
    database: Session,
    problem_id: Optional[int] = None,
    competition_run_id: Optional[str] = None,
) -> list[str]:
    statement = select(CompetitionRun).where(
        CompetitionRun.status == COMPETITION_RUN_STATUS_RUNNING
    )
    if problem_id is not None:
        statement = statement.where(CompetitionRun.problem_id == problem_id)
    if competition_run_id is not None:
        statement = statement.where(CompetitionRun.id == competition_run_id)

    reconciled_run_ids = []
    with COMPETITION_RECONCILIATION_LOCK:
        running_runs = list(database.scalars(statement).all())
        for competition_run in running_runs:
            if _reconcile_competition_run_if_needed(database, competition_run):
                reconciled_run_ids.append(competition_run.id)
    return reconciled_run_ids


def _run_competition_models_background(
    problem: Problem,
    model_names: list[str],
    competition_run_id: str,
    session_factory: sessionmaker,
) -> None:
    completed_results = []
    terminal_model_names = set()
    terminal_statuses = {}
    timeout_seconds = get_model_execution_timeout_seconds()

    with session_factory() as database:
        try:
            if not model_names:
                update_competition_run_status(
                    database,
                    competition_run_id,
                    DEFAULT_COMPETITION_RUN_STATUS,
                )
                return

            executor = ThreadPoolExecutor(max_workers=max(len(model_names), 1))
            future_map = {
                executor.submit(
                    execute_model_without_persistence,
                    _build_problem_execution_copy(problem),
                    model_name,
                ): {
                    "model_name": model_name,
                    "deadline": time.monotonic() + timeout_seconds,
                }
                for model_name in model_names
            }
            pending_futures = set(future_map)

            try:
                while pending_futures:
                    nearest_deadline = min(
                        future_map[future]["deadline"]
                        for future in pending_futures
                    )
                    wait_timeout = max(
                        0.0,
                        min(0.2, nearest_deadline - time.monotonic()),
                    )
                    done_futures, pending_futures = wait(
                        pending_futures,
                        timeout=wait_timeout,
                        return_when=FIRST_COMPLETED,
                    )

                    for future in done_futures:
                        future_info = future_map[future]
                        model_name = future_info["model_name"]
                        try:
                            model_execution = future.result()
                        except ValueError as error:
                            _save_competition_result_with_retry(
                                database,
                                lambda model_name=model_name, error=error: _save_competition_adapter_error_result(
                                    database,
                                    problem,
                                    model_name,
                                    str(error),
                                    competition_run_id,
                                ),
                            )
                            completed_results.append({"status": "Adapter Error"})
                            terminal_model_names.add(model_name)
                            terminal_statuses[model_name] = "Adapter Error"
                        except Exception as error:  # pragma: no cover
                            _save_competition_result_with_retry(
                                database,
                                lambda model_name=model_name, error=error: _save_competition_adapter_error_result(
                                    database,
                                    problem,
                                    model_name,
                                    str(error),
                                    competition_run_id,
                                ),
                            )
                            completed_results.append({"status": "Adapter Error"})
                            terminal_model_names.add(model_name)
                            terminal_statuses[model_name] = "Adapter Error"
                        else:
                            saved_model = _save_competition_result_with_retry(
                                database,
                                lambda model_execution=model_execution: persist_model_execution_result(
                                    database,
                                    problem,
                                    model_execution,
                                    competition_run_id=competition_run_id,
                                ),
                            )
                            completed_results.append(
                                {"status": saved_model["execution_result"]["status"]}
                            )
                            terminal_model_names.add(model_name)
                            terminal_statuses[model_name] = saved_model["execution_result"]["status"]

                    timed_out_futures = [
                        future
                        for future in list(pending_futures)
                        if time.monotonic() >= future_map[future]["deadline"]
                    ]

                    for future in timed_out_futures:
                        pending_futures.discard(future)
                        future.cancel()
                        model_name = future_map[future]["model_name"]
                        timeout_result = apply_disabled_quality_state(
                            build_timeout_execution_result(timeout_seconds)
                        )
                        _save_competition_result_with_retry(
                            database,
                            lambda model_name=model_name, timeout_result=timeout_result: save_evaluation_result(
                                database,
                                problem.id,
                                model_name,
                                timeout_result,
                                None,
                                competition_run_id=competition_run_id,
                            ),
                        )
                        completed_results.append({"status": timeout_result["status"]})
                        terminal_model_names.add(model_name)
                        terminal_statuses[model_name] = timeout_result["status"]
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        except Exception as error:  # pragma: no cover
            for model_name in model_names:
                if model_name in terminal_model_names:
                    continue
                _save_competition_result_with_retry(
                    database,
                    lambda model_name=model_name, error=error: _save_competition_adapter_error_result(
                        database,
                        problem,
                        model_name,
                        f"Competition worker failed: {error}",
                        competition_run_id,
                    ),
                )
                completed_results.append({"status": "Adapter Error"})
                terminal_model_names.add(model_name)
                terminal_statuses[model_name] = "Adapter Error"
        finally:
            _persist_missing_competition_rows(
                database,
                problem,
                competition_run_id,
                model_names,
                terminal_statuses,
            )
            update_competition_run_status(
                database,
                competition_run_id,
                _determine_competition_run_status(completed_results),
            )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/models", response_model=list[ModelInfoResponse])
def list_models() -> list[dict]:
    return get_active_model_catalog()


@app.get("/problems", response_model=list[ProblemResponse])
def list_problems(database: Session = Depends(get_database)) -> list[Problem]:
    return list(database.scalars(select(Problem).order_by(Problem.id)).all())


@app.get("/problems/{problem_id}", response_model=ProblemResponse)
def get_problem(
    problem_id: int,
    database: Session = Depends(get_database),
) -> Problem:
    problem = database.get(Problem, problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    return problem


@app.get("/problems/{problem_id}/prompt", response_model=PromptResponse)
def get_problem_prompt(
    problem_id: int,
    database: Session = Depends(get_database),
) -> PromptResponse:
    problem = database.get(Problem, problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    return PromptResponse(
        problem_id=problem.id,
        prompt=build_problem_prompt(problem),
    )


@app.get("/problems/{problem_id}/sample-harness", response_model=HarnessResponse)
def get_sample_harness(
    problem_id: int,
    database: Session = Depends(get_database),
) -> HarnessResponse:
    problem = database.get(Problem, problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    if is_universal_problem(problem):
        raise HTTPException(
            status_code=400,
            detail="Sample harness is only available for legacy Python problems.",
        )

    return HarnessResponse(
        problem_id=problem.id,
        harness=build_python_test_harness(SAMPLE_TWO_SUM_SOLUTION),
    )


@app.post("/problems/{problem_id}/judge-sample", response_model=JudgeResultResponse)
def judge_sample_solution(
    problem_id: int,
    database: Session = Depends(get_database),
) -> dict:
    problem = database.get(Problem, problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    if is_universal_problem(problem):
        raise HTTPException(
            status_code=400,
            detail="judge-sample is only available for legacy Python problems.",
        )

    harness = build_python_test_harness(SAMPLE_TWO_SUM_SOLUTION)
    result = enrich_execution_result(run_python_code(harness))
    saved_result = save_evaluation_result(
        database,
        problem.id,
        "hardcoded_sample",
        result,
    )

    return {"result_id": saved_result.id, **result}


@app.post("/problems/{problem_id}/run-model", response_model=ModelRunResponse)
def run_model_solution(
    problem_id: int,
    request: ModelRunRequest,
    database: Session = Depends(get_database),
) -> dict:
    problem = database.get(Problem, problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    try:
        return execute_and_save_model(database, problem, request.model_name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post(
    "/problems/{problem_id}/run-competition",
    response_model=CompetitionResponse,
    status_code=202,
)
def run_competition(
    problem_id: int,
    request: CompetitionRequest,
    database: Session = Depends(get_database),
) -> dict:
    problem = database.get(Problem, problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    model_names = (
        get_default_competition_models()
        if request.model_names is None
        else request.model_names
    )
    competition_run_id = str(uuid4())
    save_competition_run(
        database,
        problem.id,
        competition_run_id,
        len(model_names),
        COMPETITION_RUN_STATUS_RUNNING,
        model_names,
    )
    problem_snapshot = _build_problem_execution_copy(problem)
    session_factory = sessionmaker(
        bind=database.get_bind(),
        autocommit=False,
        autoflush=False,
    )
    initial_response = get_competition_run_response(problem, competition_run_id, database)
    threading.Thread(
        target=_run_competition_models_background,
        args=(
            problem_snapshot,
            model_names,
            competition_run_id,
            session_factory,
        ),
        daemon=True,
    ).start()

    return initial_response


@app.get("/results", response_model=list[EvaluationResultResponse])
def list_results(
    database: Session = Depends(get_database),
) -> list[dict]:
    statement = (
        select(EvaluationResult)
        .options(selectinload(EvaluationResult.test_results))
        .order_by(
        EvaluationResult.created_at.desc(),
        EvaluationResult.id.desc(),
    )
    )
    problems = {
        problem.id: problem
        for problem in database.scalars(select(Problem)).all()
    }
    return [
        serialize_evaluation_result(result, problems.get(result.problem_id))
        for result in database.scalars(statement).all()
    ]


@app.get(
    "/problems/{problem_id}/results",
    response_model=list[EvaluationResultResponse],
)
def get_problem_results(
    problem_id: int,
    database: Session = Depends(get_database),
) -> list[dict]:
    problem = database.get(Problem, problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    statement = (
        select(EvaluationResult)
        .options(selectinload(EvaluationResult.test_results))
        .where(EvaluationResult.problem_id == problem_id)
        .order_by(
            EvaluationResult.created_at.desc(),
            EvaluationResult.id.desc(),
        )
    )
    return [
        serialize_evaluation_result(result, problem)
        for result in database.scalars(statement).all()
    ]


@app.get("/leaderboard", response_model=LeaderboardResponse)
def get_leaderboard(
    problem_id: Optional[int] = None,
    database: Session = Depends(get_database),
    mode: str = "best",
) -> dict:
    if mode != "best":
        raise HTTPException(status_code=400, detail="Unsupported leaderboard mode")

    statement = (
        select(EvaluationResult)
        .options(selectinload(EvaluationResult.test_results))
        .order_by(
            EvaluationResult.created_at.desc(),
            EvaluationResult.id.desc(),
        )
    )

    if problem_id is not None:
        statement = statement.where(EvaluationResult.problem_id == problem_id)

    results = list(database.scalars(statement).all())
    problem_ids = {result.problem_id for result in results}
    problems = {
        problem.id: problem
        for problem in database.scalars(
            select(Problem).where(Problem.id.in_(problem_ids))
        ).all()
    }
    return {
        "problem_id": problem_id,
        "leaderboard": build_leaderboard(results, problems),
    }


@app.get(
    "/problems/{problem_id}/competition-runs/latest",
    response_model=CompetitionResponse,
)
def get_latest_competition_run(
    problem_id: int,
    database: Session = Depends(get_database),
) -> dict:
    problem = database.get(Problem, problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    reconcile_stale_competition_runs(database, problem_id=problem_id)

    latest_run_id = database.scalar(
        select(CompetitionRun.id)
        .where(CompetitionRun.problem_id == problem_id)
        .order_by(CompetitionRun.created_at.desc())
        .limit(1)
    )

    if not latest_run_id:
        raise HTTPException(status_code=404, detail="No competition run found")

    return get_competition_run_response(problem, latest_run_id, database)


@app.get(
    "/problems/{problem_id}/competition-runs/{competition_run_id}",
    response_model=CompetitionResponse,
)
def get_competition_run(
    problem_id: int,
    competition_run_id: str,
    database: Session = Depends(get_database),
) -> dict:
    problem = database.get(Problem, problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    reconcile_stale_competition_runs(
        database,
        problem_id=problem_id,
        competition_run_id=competition_run_id,
    )

    return get_competition_run_response(problem, competition_run_id, database)


@app.post(
    "/admin/problems",
    response_model=AdminProblemSummaryResponse,
    status_code=201,
)
def import_admin_problem(
    definition: dict,
    overwrite: bool = False,
    database: Session = Depends(get_database),
) -> dict:
    try:
        validate_problem_definition(definition, Path("request.json"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    problem_key = definition["id"]

    if SAFE_PROBLEM_KEY_PATTERN.fullmatch(problem_key) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Problem id may only contain lowercase letters, numbers, "
                "underscores, and hyphens."
            ),
        )

    problem_file = PROBLEM_BANK_PATH / f"{problem_key}.json"

    if problem_file.exists() and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Problem {problem_key} already exists. "
                "Use overwrite=true to replace it."
            ),
        )

    PROBLEM_BANK_PATH.mkdir(parents=True, exist_ok=True)
    problem_file.write_text(
        json.dumps(definition, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    problem = upsert_problem_definition(database, definition)
    database.commit()
    database.refresh(problem)

    return {
        "id": problem.id,
        "problem_key": problem.problem_key,
        "title": problem.title,
        "type": problem.problem_type,
        "language": definition["language"],
        "file_count": len(definition["files"]),
    }


@app.get("/admin/problems/{problem_key}/definition")
def get_admin_problem_definition(problem_key: str) -> dict:
    if SAFE_PROBLEM_KEY_PATTERN.fullmatch(problem_key) is None:
        raise HTTPException(status_code=400, detail="Invalid problem key")

    problem_file = PROBLEM_BANK_PATH / f"{problem_key}.json"

    if not problem_file.exists():
        raise HTTPException(status_code=404, detail="Problem definition not found")

    try:
        return load_problem_definition(problem_file)
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get(
    "/results/{result_id}/comparison",
    response_model=ResultComparisonResponse,
)
def get_result_comparison(
    result_id: int,
    database: Session = Depends(get_database),
) -> dict:
    saved_result = database.get(EvaluationResult, result_id)

    if saved_result is None:
        raise HTTPException(status_code=404, detail="Evaluation result not found")

    problem = database.get(Problem, saved_result.problem_id)

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    return build_result_comparison_response(saved_result, problem)


@app.post(
    "/results/{result_id}/ai-analysis",
    response_model=AIAnalysisResponse,
)
def run_result_ai_analysis(
    result_id: int,
    database: Session = Depends(get_database),
) -> dict:
    saved_result = database.get(EvaluationResult, result_id)

    if saved_result is None:
        raise HTTPException(status_code=404, detail="Evaluation result not found")

    problem = database.get(Problem, saved_result.problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    eligibility_result = {
        "status": saved_result.status,
        "score_earned": saved_result.score_earned,
        "score_possible": saved_result.score_possible,
        "score_percentage": saved_result.score_percentage,
    }
    if not is_ai_analysis_eligible_result(eligibility_result):
        raise HTTPException(status_code=409, detail=AI_ANALYSIS_DISABLED_MESSAGE)

    if (
        (saved_result.ai_analysis_status or "") == "completed"
        and saved_result.ai_analysis_json
    ):
        return build_ai_analysis_response(saved_result, cached=True)

    candidate_files = _extract_candidate_files_from_comparison(saved_result)
    reference_files = _extract_reference_files(problem)
    if not candidate_files or not reference_files:
        raise HTTPException(
            status_code=409,
            detail="AI Analysis requires stored candidate and reference solution data.",
        )

    problem_definition = get_universal_definition(problem)
    execution_result = serialize_evaluation_result(saved_result, problem)
    review_mode = determine_ai_analysis_review_mode(execution_result)
    build_ai_analysis_input(
        problem_definition,
        candidate_files,
        reference_files,
        execution_result,
        review_mode,
    )

    try:
        analysis_payload = generate_ai_analysis(
            problem_definition,
            candidate_files,
            reference_files,
            execution_result,
        )
    except Exception as error:
        review_error = str(error).strip() or "The AI Code Review could not be generated."
        _persist_ai_analysis_failure(database, saved_result, review_error)
        raise HTTPException(
            status_code=503,
            detail=review_error,
        ) from error
    saved_result = _persist_completed_ai_analysis(
        database,
        saved_result,
        analysis_payload,
    )
    return build_ai_analysis_response(saved_result, cached=False)
