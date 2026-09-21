import copy
import hashlib
import importlib
import json
import logging
import math
import os
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)

AI_ANALYSIS_DISABLED_MESSAGE = (
    "AI Code Review is available only for functionally perfect Accepted results or Wrong Answer results."
)
AI_REVIEW_PROVIDER_MOCK = "mock"
AI_REVIEW_PROVIDER_OPENROUTER = "openrouter"
AI_REVIEW_ALLOWED_PROVIDERS = {
    AI_REVIEW_PROVIDER_MOCK,
    AI_REVIEW_PROVIDER_OPENROUTER,
}
AI_REVIEW_DEFAULT_TIMEOUT_SECONDS = 120.0
AI_REVIEW_DEFAULT_MAX_OUTPUT_TOKENS = 1800
AI_REVIEW_DEFAULT_MAX_INPUT_CHARS = 60000
AI_ANALYSIS_PROMPT_VERSION = "ai-code-review-v3"
AI_ANALYSIS_WRONG_ANSWER_PROMPT_VERSION = "ai-code-review-wrong-answer-v1"
AI_ANALYSIS_RUBRIC_VERSION = "ai-code-review-rubric-v1"
AI_ANALYSIS_REVIEWER_MODEL = "mock-ai-reviewer"
OPENROUTER_REVIEW_API_URL = "https://openrouter.ai/api/v1/chat/completions"
REVIEW_OVERALL_ASSESSMENTS = {
    "strong",
    "adequate",
    "needs_improvement",
}
REVIEW_CATEGORY_ASSESSMENTS = REVIEW_OVERALL_ASSESSMENTS | {"not_applicable"}
REVIEW_CATEGORIES = [
    ("readability_maintainability", "Readability and Maintainability"),
    ("structural_quality", "Structural Quality"),
    ("language_framework_practices", "Language and Framework Practices"),
    ("efficiency_proportionality", "Efficiency and Proportionality"),
    ("scope_requirement_interpretation", "Scope and Requirement Interpretation"),
]
AI_ANALYSIS_REVIEW_MODE_ACCEPTED = "accepted_review"
AI_ANALYSIS_REVIEW_MODE_WRONG_ANSWER = "wrong_answer_diagnosis"
REVIEW_JSON_SCHEMA = {
    "name": "ai_code_review",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "status",
            "overall_assessment",
            "summary",
            "categories",
            "strengths",
            "improvements",
            "reference_comparison",
            "reviewer",
        ],
        "properties": {
            "status": {"type": "string", "enum": ["completed"]},
            "overall_assessment": {
                "type": "string",
                "enum": ["strong", "adequate", "needs_improvement"],
            },
            "summary": {"type": "string"},
            "categories": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "name", "assessment", "explanation"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "assessment": {
                            "type": "string",
                            "enum": [
                                "strong",
                                "adequate",
                                "needs_improvement",
                                "not_applicable",
                            ],
                        },
                        "explanation": {"type": "string"},
                    },
                },
            },
            "strengths": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "explanation"],
                    "properties": {
                        "title": {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                },
            },
            "improvements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["issue", "evidence", "explanation", "suggestion", "file"],
                    "properties": {
                        "issue": {"type": "string"},
                        "evidence": {"type": "string"},
                        "explanation": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "file": {"type": "string"},
                    },
                },
            },
            "reference_comparison": {
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "meaningful_differences"],
                "properties": {
                    "summary": {"type": "string"},
                    "meaningful_differences": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "candidate_evidence",
                                "reference_evidence",
                                "explanation",
                            ],
                            "properties": {
                                "candidate_evidence": {"type": "string"},
                                "reference_evidence": {"type": "string"},
                                "explanation": {"type": "string"},
                                "candidate_file": {"type": "string"},
                                "reference_file": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "reviewer": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "provider",
                    "requested_model",
                    "used_model",
                    "prompt_version",
                    "rubric_version",
                ],
                "properties": {
                    "provider": {"type": "string"},
                    "requested_model": {"type": "string"},
                    "used_model": {"type": "string"},
                    "prompt_version": {"type": "string"},
                    "rubric_version": {"type": "string"},
                },
            },
        },
    },
}


def is_functionally_perfect_result(result: dict) -> bool:
    status = str(result.get("status", "")).strip()
    score_earned = result.get("score_earned")
    score_possible = result.get("score_possible")
    score_percentage = result.get("score_percentage")

    if status != "Accepted":
        return False
    if score_earned is None or score_possible is None or score_percentage is None:
        return False

    try:
        earned_value = float(score_earned)
        possible_value = float(score_possible)
        percentage_value = float(score_percentage)
    except (TypeError, ValueError):
        return False

    if possible_value <= 0:
        return False

    return math.isclose(earned_value, possible_value, rel_tol=1e-9, abs_tol=1e-9) and math.isclose(
        percentage_value,
        100.0,
        rel_tol=1e-9,
        abs_tol=1e-6,
    )


def determine_ai_analysis_review_mode(result: dict) -> Optional[str]:
    status = str(result.get("status", "")).strip()
    if status == "Wrong Answer":
        return AI_ANALYSIS_REVIEW_MODE_WRONG_ANSWER
    if is_functionally_perfect_result(result):
        return AI_ANALYSIS_REVIEW_MODE_ACCEPTED
    return None


def is_ai_analysis_eligible_result(result: dict) -> bool:
    return determine_ai_analysis_review_mode(result) is not None


def _get_ai_review_provider() -> str:
    provider = os.getenv("AI_REVIEW_PROVIDER", AI_REVIEW_PROVIDER_MOCK).strip().lower()
    if provider not in AI_REVIEW_ALLOWED_PROVIDERS:
        raise ValueError(
            "AI Code Review provider is invalid. Supported values are: mock, openrouter."
        )
    return provider


def get_ai_review_prompt_version() -> str:
    return os.getenv("AI_REVIEW_PROMPT_VERSION", AI_ANALYSIS_PROMPT_VERSION).strip() or AI_ANALYSIS_PROMPT_VERSION


def get_ai_review_rubric_version() -> str:
    return os.getenv("AI_REVIEW_RUBRIC_VERSION", AI_ANALYSIS_RUBRIC_VERSION).strip() or AI_ANALYSIS_RUBRIC_VERSION


def get_ai_review_timeout_seconds() -> float:
    raw_value = os.getenv("AI_REVIEW_TIMEOUT_SECONDS", str(AI_REVIEW_DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        timeout_value = float(raw_value)
    except ValueError:
        return AI_REVIEW_DEFAULT_TIMEOUT_SECONDS

    if not math.isfinite(timeout_value) or timeout_value <= 0:
        return AI_REVIEW_DEFAULT_TIMEOUT_SECONDS

    return timeout_value


def get_ai_review_max_output_tokens() -> int:
    raw_value = os.getenv(
        "AI_REVIEW_MAX_OUTPUT_TOKENS",
        str(AI_REVIEW_DEFAULT_MAX_OUTPUT_TOKENS),
    ).strip()
    try:
        max_tokens = int(raw_value)
    except ValueError:
        return AI_REVIEW_DEFAULT_MAX_OUTPUT_TOKENS

    return max(max_tokens, 1)


def get_ai_review_max_input_chars() -> int:
    raw_value = os.getenv(
        "AI_REVIEW_MAX_INPUT_CHARS",
        str(AI_REVIEW_DEFAULT_MAX_INPUT_CHARS),
    ).strip()
    try:
        max_chars = int(raw_value)
    except ValueError:
        return AI_REVIEW_DEFAULT_MAX_INPUT_CHARS

    return max(max_chars, 1)


def parse_ai_review_models() -> List[str]:
    configured_models = []
    raw_value = os.getenv("AI_REVIEW_MODELS", "")

    for model_name in raw_value.split(","):
        cleaned_model_name = model_name.strip()
        if not cleaned_model_name:
            continue
        if not cleaned_model_name.endswith(":free"):
            logger.warning(
                "Skipping AI review model '%s' because only :free OpenRouter models are allowed.",
                cleaned_model_name,
            )
            continue
        configured_models.append(cleaned_model_name)

    return configured_models


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_solution_files(files: List[dict]) -> str:
    normalized_files = []
    for file_definition in files:
        normalized_files.append(
            {
                "path": file_definition.get("path", ""),
                "language": file_definition.get("language"),
                "content": file_definition.get("content", ""),
            }
        )
    normalized_files.sort(key=lambda file_definition: file_definition.get("path", ""))
    return _sha256_text(_stable_json_dumps(normalized_files))


def _assessment_from_ratio(ratio: float) -> str:
    if ratio >= 0.9:
        return "strong"
    if ratio >= 0.75:
        return "adequate"
    return "needs_improvement"


def _assessment_from_legacy_score(score: Optional[float]) -> str:
    if score is None:
        return "adequate"

    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        return "adequate"

    if numeric_score >= 90:
        return "strong"
    if numeric_score >= 75:
        return "adequate"
    return "needs_improvement"


def _build_strength(title: str, explanation: str) -> dict:
    return {
        "title": title,
        "explanation": explanation,
    }


def _build_reviewer_block(provider: str, requested_model: str, used_model: str) -> dict:
    return {
        "provider": provider,
        "requested_model": requested_model,
        "used_model": used_model,
        "prompt_version": get_ai_review_prompt_version(),
        "rubric_version": get_ai_review_rubric_version(),
    }


def _get_prompt_version_for_mode(review_mode: str) -> str:
    if review_mode == AI_ANALYSIS_REVIEW_MODE_WRONG_ANSWER:
        return AI_ANALYSIS_WRONG_ANSWER_PROMPT_VERSION
    return get_ai_review_prompt_version()


def _build_reviewer_block_for_mode(
    provider: str,
    requested_model: str,
    used_model: str,
    review_mode: str,
) -> dict:
    reviewer = _build_reviewer_block(provider, requested_model, used_model)
    reviewer["prompt_version"] = _get_prompt_version_for_mode(review_mode)
    return reviewer


def _build_audit_block(
    candidate_files: List[dict],
    reference_files: List[dict],
    reviewer_output_hash: str,
) -> dict:
    return {
        "candidate_content_hash": _hash_solution_files(candidate_files),
        "reference_content_hash": _hash_solution_files(reference_files),
        "reviewer_output_hash": reviewer_output_hash,
        "evidence_verification": {
            "verified_improvements": 0,
            "suppressed_improvements": 0,
            "verified_reference_differences": 0,
            "suppressed_reference_differences": 0,
        },
    }


def build_ai_analysis_input(
    problem_definition: Optional[dict],
    candidate_files: List[dict],
    reference_files: List[dict],
    result: dict,
    review_mode: Optional[str] = None,
) -> dict:
    definition = problem_definition or {}
    instructions = definition.get("instructions", {}) if isinstance(definition, dict) else {}
    definition_files = definition.get("files", []) if isinstance(definition, dict) else []
    editable_context = []
    readonly_context = []

    for file_definition in definition_files:
        file_record = {
            "path": file_definition.get("path", ""),
            "language": file_definition.get("language"),
            "content": file_definition.get("content", ""),
            "role": file_definition.get("role", ""),
        }
        if file_definition.get("role") == "editable":
            editable_context.append(file_record)
        elif file_definition.get("includeInPrompt"):
            readonly_context.append(file_record)

    review_input = {}
    review_input["assignment"] = {
        "title": definition.get("title"),
        "description": definition.get("description"),
        "student_prompt": instructions.get("studentPrompt"),
        "language": definition.get("language"),
        "evaluator_type": definition.get("evaluatorType"),
        "functional_result_confirmed": is_functionally_perfect_result(result),
        "functional_confirmation": (
            "The candidate passed all required functional tests."
            if determine_ai_analysis_review_mode(result)
            == AI_ANALYSIS_REVIEW_MODE_ACCEPTED
            else "The candidate did not pass all required functional tests."
        ),
    }
    review_input["context_files"] = {
        "editable_starter_files": editable_context,
        "read_only_context_files": readonly_context,
    }
    review_input["candidate_solution_files"] = [
        {
            "path": file_definition.get("path", ""),
            "language": file_definition.get("language"),
            "content": file_definition.get("content", ""),
        }
        for file_definition in candidate_files
    ]
    review_input["reference_solution_files"] = [
        {
            "path": file_definition.get("path", ""),
            "language": file_definition.get("language"),
            "content": file_definition.get("content", ""),
        }
        for file_definition in reference_files
    ]
    if review_mode == AI_ANALYSIS_REVIEW_MODE_WRONG_ANSWER:
        review_input["diagnostic_context"] = _build_wrong_answer_diagnostic_context(
            result
        )
    return review_input


def _serialize_review_input(review_input: dict) -> str:
    return _stable_json_dumps(review_input)


def _fit_review_input_to_limit(review_input: dict, max_chars: int) -> Tuple[dict, int]:
    fitted_input = copy.deepcopy(review_input)
    current_length = len(_serialize_review_input(fitted_input))
    if current_length <= max_chars:
        return fitted_input, current_length

    fitted_input["context_files"]["read_only_context_files"] = []
    current_length = len(_serialize_review_input(fitted_input))
    if current_length <= max_chars:
        return fitted_input, current_length

    raise ValueError(
        "The candidate and reference content exceed the configured AI Code Review input limit."
    )


def _build_reviewer_system_prompt() -> str:
    return (
        "You are reviewing a programming submission that has already passed all required\n"
        "functional tests. Do not re-grade functionality or correctness of test behavior.\n\n"
        "Your job is to assess code quality against the assignment requirements only:\n"
        "readability, maintainability, structure, language/framework practices, and\n"
        "efficiency relative to the task's scope.\n\n"
        "Rules:\n"
        "- It is a fully acceptable outcome to report no meaningful improvements. Do not\n"
        "  invent criticism to fill a section. A clean, well-scoped solution should\n"
        "  receive a short, positive review, not padded feedback.\n"
        "- Ignore removed or absent placeholder/scaffold content (e.g. TODO comments,\n"
        "  starter boilerplate) entirely. This is expected and never worth mentioning.\n"
        "- Do not comment on naming, formatting, ordering, or syntax choices unless they\n"
        "  materially harm readability, maintainability, correctness, or efficiency.\n"
        "  \"Different from a common convention\" is not by itself material.\n"
        "- You will be given a reference solution. It is one valid implementation, not\n"
        "  a required shape. Form your assessment of the candidate against the\n"
        "  assignment requirements BEFORE consulting the reference solution. Only\n"
        "  bring the reference in afterward, and only to note a difference with\n"
        "  material engineering impact (e.g. a correctness edge case, a performance\n"
        "  concern, or a maintainability risk) that the candidate's approach\n"
        "  introduces. Never mention a difference that is purely stylistic, structural\n"
        "  preference, or syntactic.\n"
        "- Do not mention or infer which AI model produced the candidate solution.\n\n"
        "Output format:\n"
        "- Plain text only. No JSON, no Markdown code fences.\n"
        "- Use these headings, in this order, only when they have real content:\n"
        "  Overall Assessment (always include)\n"
        "  Strengths (always include)\n"
        "  Areas for Improvement (omit entirely if none — do not write a placeholder line)\n"
        "  Notable Differences from Reference (omit entirely if none)\n"
        "  Final Takeaway (always include)\n"
        "- Be concise. Prioritize substance over completeness of sections.\n"
    )


def _build_wrong_answer_reviewer_system_prompt() -> str:
    return (
        "You are reviewing a programming submission that did not pass all required functional tests.\n\n"
        "Your job is to diagnose the likely reasons for failure using:\n"
        "- the assignment requirements\n"
        "- the candidate solution\n"
        "- the provided test-result summaries and assertion messages\n"
        "- the reference solution as one valid implementation\n\n"
        "Do not simply say that tests failed.\n\n"
        "Explain what the candidate likely misunderstood or implemented differently.\n\n"
        "Prioritize actionable engineering feedback.\n\n"
        "Rules:\n"
        "- Identify which parts of the solution appear correct.\n"
        "- Identify the most important likely cause or causes of the failed tests.\n"
        "- Connect your explanation to specific candidate code or structure when possible.\n"
        "- Distinguish between a true requirement issue and a harmless stylistic difference.\n"
        "- Do not criticize naming, formatting, whitespace, ordering, or equivalent syntax unless it materially contributes to the failure.\n"
        "- Do not assume the reference solution is the only valid implementation.\n"
        "- Use the failed test summaries as evidence, but do not invent hidden test behavior beyond what is provided.\n"
        "- Do not mention or infer which AI model produced the candidate.\n"
        "- Do not recommend changes that contradict tests the candidate already passed.\n"
        "- If the likely cause cannot be determined confidently from the available information, say so rather than inventing an explanation.\n\n"
        "Output format:\n"
        "- Plain text only\n"
        "- No JSON\n"
        "- No Markdown code fences\n"
        "- Be concise and specific\n\n"
        "Use headings when useful:\n\n"
        "Failure Diagnosis\n"
        "What Was Done Correctly\n"
        "What Likely Caused the Failure\n"
        "Recommended Fixes\n"
        "Reference Comparison\n"
        "Final Takeaway\n\n"
        "Do not force empty sections.\n"
    )


def _build_reviewer_user_prompt(review_input: dict, review_mode: str) -> str:
    if review_mode == AI_ANALYSIS_REVIEW_MODE_WRONG_ANSWER:
        return (
            "Review this candidate solution to diagnose why it did not pass all required functional tests.\n\n"
            "Use only the assignment requirements, context files, candidate solution files, visible failed-test summaries,\n"
            "and the reference solution as one valid implementation.\n"
            "Do not infer hidden test source code or hidden evaluator details.\n\n"
            "Keep the response concise enough for the configured token limit.\n\n"
            "Input JSON:\n"
            f"{_serialize_review_input(review_input)}"
        )
    return (
        "Review this functionally correct candidate solution against the assignment\n"
        "requirements below. The candidate has already passed all required functional\n"
        "tests — do not re-assess correctness of behavior.\n\n"
        "First, assess the candidate independently using only the assignment,\n"
        "description, context files, and candidate solution files. Only after forming\n"
        "that assessment, consult the reference solution solely to check for material\n"
        "engineering differences as defined in your instructions. If you find none,\n"
        "omit that section.\n\n"
        "Keep the response concise enough for the configured token limit.\n\n"
        "Input JSON:\n"
        f"{_serialize_review_input(review_input)}"
    )


def _extract_safe_assertion_messages(assertions: Any) -> List[dict]:
    safe_assertions = []
    for assertion in assertions or []:
        if not isinstance(assertion, dict):
            continue
        safe_entry = {}
        message = assertion.get("message")
        if isinstance(message, str) and message.strip():
            safe_entry["message"] = message.strip()
        if "actual" in assertion:
            safe_entry["actual"] = assertion.get("actual")
        if "expected" in assertion:
            safe_entry["expected"] = assertion.get("expected")
        if safe_entry:
            safe_assertions.append(safe_entry)
    return safe_assertions


def _build_wrong_answer_diagnostic_context(result: dict) -> dict:
    safe_failed_tests = []
    test_results = result.get("test_results", []) or []

    for test_result in test_results:
        if not isinstance(test_result, dict):
            continue
        if str(test_result.get("status", "")).strip() == "passed":
            continue

        safe_failed_tests.append(
            {
                "name": test_result.get("name"),
                "status": test_result.get("status"),
                "points_earned": test_result.get("points_earned"),
                "points_possible": test_result.get("points_possible"),
                "message": test_result.get("message"),
                "assertions": _extract_safe_assertion_messages(
                    test_result.get("assertions", [])
                ),
                "runtime_error": (
                    str(test_result.get("message", "")).strip()
                    if str(test_result.get("status", "")).strip()
                    in {"failed", "runtime_error", "timeout"}
                    else None
                ),
            }
        )

    return {
        "functional_score": {
            "score_earned": result.get("score_earned"),
            "score_possible": result.get("score_possible"),
            "score_percentage": result.get("score_percentage"),
        },
        "passed_test_count": result.get("passed_tests"),
        "failed_test_count": result.get("failed_tests"),
        "failed_tests": safe_failed_tests,
    }


def _extract_openrouter_message(response_text: str) -> str:
    try:
        parsed_payload = json.loads(response_text)
    except (TypeError, json.JSONDecodeError):
        return response_text.strip()

    if isinstance(parsed_payload, dict):
        error_block = parsed_payload.get("error")
        if isinstance(error_block, dict):
            message = error_block.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error_block, str) and error_block.strip():
            return error_block.strip()

    return response_text.strip()


def _is_timeout_error(error: Exception) -> bool:
    error_name = type(error).__name__.lower()
    error_message = str(error).lower()
    return (
        "timeout" in error_name
        or "deadline" in error_name
        or "timed out" in error_message
        or "deadline exceeded" in error_message
    )


def _normalize_openrouter_review_error(status_code: int, response_text: str) -> str:
    message = _extract_openrouter_message(response_text)
    normalized = message.lower()

    if status_code in {401, 403}:
        return "The AI Code Review reviewer credentials were rejected by OpenRouter."
    if status_code == 404:
        return "The configured AI Code Review reviewer model is invalid or unavailable."
    if status_code == 429:
        return "The AI Code Review reviewer is currently rate limited. Please try again."
    if "quota" in normalized or "credits" in normalized:
        return "The AI Code Review reviewer quota is unavailable right now. Please try again later."

    return "The AI Code Review provider request failed."


def _build_plain_text_analysis_payload(
    review_text: str,
    requested_model: str,
    used_model: str,
    candidate_files: List[dict],
    reference_files: List[dict],
    review_mode: str,
) -> dict:
    return {
        "format": "plain_text",
        "review_mode": review_mode,
        "review_text": review_text.strip(),
        "reviewer": _build_reviewer_block_for_mode(
            AI_REVIEW_PROVIDER_OPENROUTER,
            requested_model,
            used_model,
            review_mode,
        ),
        "audit": _build_audit_block(
            candidate_files,
            reference_files,
            _sha256_text(review_text.strip()),
        ),
    }


def _build_mock_payload(
    candidate_files: List[dict],
    reference_files: List[dict],
    review_mode: str,
) -> dict:
    del candidate_files, reference_files
    if review_mode == AI_ANALYSIS_REVIEW_MODE_WRONG_ANSWER:
        review_text = (
            "Failure Diagnosis\n"
            "The candidate is close, but at least one required behavior or structural detail does not match the assignment.\n\n"
            "What Was Done Correctly\n"
            "- Some required elements or logic are present, which is why part of the test suite passed.\n\n"
            "What Likely Caused the Failure\n"
            "- One or more remaining tests likely depend on a missing requirement, incorrect structure, or mismatched output.\n\n"
            "Recommended Fixes\n"
            "- Compare the failed test summaries against the assignment requirements and correct the first missing or mismatched behavior.\n\n"
            "Final Takeaway\n"
            "This submission is partially correct, but it still needs targeted fixes before it will pass all required tests."
        )
    else:
        review_text = (
            "Overall assessment\n"
            "This solution is functionally correct, appropriately scoped, and easy to follow.\n\n"
            "Strengths\n"
            "- Stays focused on the requested behavior.\n"
            "- Uses a clear structure that should be easy to maintain.\n\n"
            "Areas for improvement\n"
            "- No major issues stand out in this candidate.\n\n"
            "Meaningful differences from the reference solution\n"
            "- The candidate may use different naming or structure, but nothing here suggests a worse implementation.\n\n"
            "Final takeaway\n"
            "This is a solid solution for the assignment."
        )
    return {
        "format": "plain_text",
        "review_mode": review_mode,
        "review_text": review_text,
        "reviewer": _build_reviewer_block_for_mode(
            AI_REVIEW_PROVIDER_MOCK,
            AI_ANALYSIS_REVIEWER_MODEL,
            AI_ANALYSIS_REVIEWER_MODEL,
            review_mode,
        ),
        "audit": _build_audit_block(
            [],
            [],
            _sha256_text(review_text),
        ),
    }


def generate_mock_ai_analysis(
    problem_definition: Optional[dict],
    candidate_files: List[dict],
    reference_files: List[dict],
    result: dict,
) -> dict:
    del problem_definition

    review_mode = determine_ai_analysis_review_mode(result)
    if not review_mode:
        raise ValueError(AI_ANALYSIS_DISABLED_MESSAGE)

    return _build_mock_payload(candidate_files, reference_files, review_mode)


def _build_openrouter_request_body(
    model_name: str,
    review_input: dict,
    review_mode: str,
) -> dict:
    return {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    _build_wrong_answer_reviewer_system_prompt()
                    if review_mode == AI_ANALYSIS_REVIEW_MODE_WRONG_ANSWER
                    else _build_reviewer_system_prompt()
                ),
            },
            {
                "role": "user",
                "content": _build_reviewer_user_prompt(review_input, review_mode),
            },
        ],
        "temperature": 0,
        "max_tokens": get_ai_review_max_output_tokens(),
    }


def _request_openrouter_review(
    requests_module: Any,
    api_key: str,
    model_name: str,
    review_input: dict,
    review_mode: str,
) -> Tuple[str, str]:
    try:
        response = requests_module.post(
            OPENROUTER_REVIEW_API_URL,
            json=_build_openrouter_request_body(
                model_name,
                review_input,
                review_mode,
            ),
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
            timeout=get_ai_review_timeout_seconds(),
        )
    except requests_module.RequestException as error:
        if _is_timeout_error(error):
            raise ValueError(
                "AI Code Review request timed out after "
                + str(int(get_ai_review_timeout_seconds()))
                + " seconds."
            ) from error
        raise ValueError(
            "The AI Code Review provider could not be reached."
        ) from error

    if response.status_code != 200:
        raise ValueError(_normalize_openrouter_review_error(response.status_code, response.text))

    try:
        response_data = response.json()
    except ValueError as error:
        raise ValueError("The AI Code Review provider returned a malformed JSON envelope.") from error

    raw_response = (
        response_data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not isinstance(raw_response, str):
        raise ValueError("The AI Code Review provider returned an empty review.")

    trimmed_response = raw_response.strip()
    if not trimmed_response:
        raise ValueError("The AI Code Review provider returned an empty response.")

    used_model = str(response_data.get("model") or model_name)
    return trimmed_response, used_model


def _run_openrouter_ai_analysis(
    review_input: dict,
    candidate_files: List[dict],
    reference_files: List[dict],
    review_mode: str,
) -> dict:
    api_key = os.getenv("AI_REVIEW_OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "AI Code Review is not configured because AI_REVIEW_OPENROUTER_API_KEY is missing."
        )

    review_models = parse_ai_review_models()
    if not review_models:
        raise ValueError(
            "AI Code Review is not configured because no free reviewer models are listed in AI_REVIEW_MODELS."
        )

    try:
        requests_module = importlib.import_module("requests")
    except ImportError as error:
        raise ValueError(
            "The requests package is not installed. Run 'pip install -r requirements.txt' to enable AI Code Review."
        ) from error

    requested_model = review_models[0]
    review_text, used_model = _request_openrouter_review(
        requests_module,
        api_key,
        requested_model,
        review_input,
        review_mode,
    )
    logger.info(
        "AI Code Review plain-text response received for model %s (length=%s).",
        requested_model,
        len(review_text),
    )
    return _build_plain_text_analysis_payload(
        review_text,
        requested_model,
        used_model,
        candidate_files,
        reference_files,
        review_mode,
    )


def generate_ai_analysis(
    problem_definition: Optional[dict],
    candidate_files: List[dict],
    reference_files: List[dict],
    result: dict,
) -> dict:
    review_mode = determine_ai_analysis_review_mode(result)
    if not review_mode:
        raise ValueError(AI_ANALYSIS_DISABLED_MESSAGE)

    review_input = build_ai_analysis_input(
        problem_definition,
        candidate_files,
        reference_files,
        result,
        review_mode,
    )
    review_input, _ = _fit_review_input_to_limit(
        review_input,
        get_ai_review_max_input_chars(),
    )

    provider = _get_ai_review_provider()
    if provider == AI_REVIEW_PROVIDER_MOCK:
        return generate_mock_ai_analysis(
            problem_definition,
            candidate_files,
            reference_files,
            result,
        )
    if provider == AI_REVIEW_PROVIDER_OPENROUTER:
        return _run_openrouter_ai_analysis(
            review_input,
            candidate_files,
            reference_files,
            review_mode,
        )

    raise ValueError("AI Code Review provider is not supported.")


def _normalize_legacy_strengths(strengths: Any) -> List[dict]:
    normalized_strengths = []
    for strength in strengths or []:
        if isinstance(strength, dict):
            title = str(strength.get("title", "")).strip()
            explanation = str(strength.get("explanation", "")).strip() or title
            if title:
                normalized_strengths.append(
                    {
                        "title": title,
                        "explanation": explanation,
                    }
                )
        elif isinstance(strength, str) and strength.strip():
            normalized_strengths.append(
                {
                    "title": strength.strip(),
                    "explanation": strength.strip(),
                }
            )
    return normalized_strengths


def _normalize_legacy_categories(categories: Any) -> List[dict]:
    normalized_categories = []
    for category in categories or []:
        if not isinstance(category, dict):
            continue
        points_possible = float(category.get("points_possible", 0) or 0)
        points_earned = float(category.get("points_earned", 0) or 0)
        ratio = 1.0 if points_possible <= 0 else points_earned / points_possible
        normalized_categories.append(
            {
                "id": str(category.get("id", "")).strip(),
                "name": str(category.get("name", "")).strip(),
                "assessment": _assessment_from_ratio(ratio),
                "explanation": str(category.get("explanation", "")).strip(),
            }
        )
    return normalized_categories


def _normalize_legacy_payload(payload: dict) -> dict:
    score = payload.get("score")
    reviewer = payload.get("reviewer", {}) if isinstance(payload.get("reviewer"), dict) else {}
    normalized_payload = {
        "status": "completed",
        "overall_assessment": _assessment_from_legacy_score(score),
        "summary": str(payload.get("summary", "")).strip()
        or "Legacy AI analysis data is available for this result.",
        "categories": _normalize_legacy_categories(payload.get("categories", [])),
        "strengths": _normalize_legacy_strengths(payload.get("strengths", [])),
        "improvements": [],
        "reference_comparison": {
            "summary": "This stored review predates the current reference-comparison format.",
            "meaningful_differences": [],
        },
        "reviewer": {
            "provider": str(reviewer.get("provider", "mock")).strip() or "mock",
            "requested_model": str(reviewer.get("requested_model", "legacy-reviewer")).strip()
            or "legacy-reviewer",
            "used_model": str(reviewer.get("used_model", "legacy-reviewer")).strip()
            or "legacy-reviewer",
            "prompt_version": str(
                reviewer.get("prompt_version", "legacy-ai-analysis")
            ).strip()
            or "legacy-ai-analysis",
            "rubric_version": "legacy-ai-analysis",
        },
        "audit": {
            "candidate_content_hash": None,
            "reference_content_hash": None,
            "reviewer_output_hash": _sha256_text(_stable_json_dumps(payload)),
            "evidence_verification": {
                "verified_improvements": 0,
                "suppressed_improvements": len(payload.get("improvements", []) or []),
                "verified_reference_differences": 0,
                "suppressed_reference_differences": 0,
            },
            "legacy_payload": True,
        },
    }

    for improvement in payload.get("improvements", []) or []:
        if not isinstance(improvement, dict):
            continue
        evidence = str(improvement.get("evidence", "")).strip()
        if not evidence:
            continue
        normalized_payload["improvements"].append(
            {
                "issue": str(improvement.get("issue", "Legacy observation")).strip()
                or "Legacy observation",
                "evidence": evidence,
                "explanation": str(improvement.get("issue", "Legacy observation")).strip()
                or "Legacy observation",
                "suggestion": str(improvement.get("suggestion", "")).strip()
                or "No suggestion was stored for this legacy review.",
                "file": str(improvement.get("file", "")).strip(),
                "evidence_verified": False,
            }
        )

    return normalized_payload


def validate_ai_analysis_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("AI Code Review payload must be an object.")

    if "overall_assessment" not in payload and "score" in payload:
        payload = _normalize_legacy_payload(payload)

    required_fields = [
        "status",
        "overall_assessment",
        "summary",
        "categories",
        "strengths",
        "improvements",
        "reference_comparison",
        "reviewer",
        "audit",
    ]
    for field_name in required_fields:
        if field_name not in payload:
            raise ValueError(
                "AI Code Review payload is missing required field: " + field_name
            )

    if payload.get("status") != "completed":
        raise ValueError("AI Code Review payload must have completed status.")

    overall_assessment = str(payload.get("overall_assessment", "")).strip()
    if overall_assessment not in REVIEW_OVERALL_ASSESSMENTS:
        raise ValueError("AI Code Review overall assessment is invalid.")

    categories = payload.get("categories")
    if not isinstance(categories, list) or not categories:
        raise ValueError("AI Code Review categories must be a non-empty list.")

    for category in categories:
        if not isinstance(category, dict):
            raise ValueError("Each AI Code Review category must be an object.")
        for field_name in ["id", "name", "assessment", "explanation"]:
            if field_name not in category:
                raise ValueError(
                    "AI Code Review category is missing required field: " + field_name
                )
        if category.get("assessment") not in REVIEW_CATEGORY_ASSESSMENTS:
            raise ValueError("AI Code Review category assessment is invalid.")

    strengths = payload.get("strengths")
    if not isinstance(strengths, list):
        raise ValueError("AI Code Review strengths must be a list.")
    for strength in strengths:
        if not isinstance(strength, dict):
            raise ValueError("Each AI Code Review strength must be an object.")
        for field_name in ["title", "explanation"]:
            if field_name not in strength:
                raise ValueError(
                    "AI Code Review strength is missing required field: " + field_name
                )

    improvements = payload.get("improvements")
    if not isinstance(improvements, list):
        raise ValueError("AI Code Review improvements must be a list.")
    for improvement in improvements:
        if not isinstance(improvement, dict):
            raise ValueError("Each AI Code Review improvement must be an object.")
        for field_name in ["issue", "evidence", "explanation", "suggestion", "file"]:
            if field_name not in improvement:
                raise ValueError(
                    "AI Code Review improvement is missing required field: " + field_name
                )

    reference_comparison = payload.get("reference_comparison")
    if not isinstance(reference_comparison, dict):
        raise ValueError("AI Code Review reference comparison must be an object.")
    for field_name in ["summary", "meaningful_differences"]:
        if field_name not in reference_comparison:
            raise ValueError(
                "AI Code Review reference comparison is missing required field: "
                + field_name
            )
    meaningful_differences = reference_comparison.get("meaningful_differences")
    if not isinstance(meaningful_differences, list):
        raise ValueError(
            "AI Code Review reference comparison differences must be a list."
        )
    for difference in meaningful_differences:
        if not isinstance(difference, dict):
            raise ValueError(
                "Each AI Code Review reference comparison difference must be an object."
            )
        for field_name in ["candidate_evidence", "reference_evidence", "explanation"]:
            if field_name not in difference:
                raise ValueError(
                    "AI Code Review reference comparison difference is missing required field: "
                    + field_name
                )

    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, dict):
        raise ValueError("AI Code Review reviewer must be an object.")
    for field_name in [
        "provider",
        "requested_model",
        "used_model",
        "prompt_version",
        "rubric_version",
    ]:
        if field_name not in reviewer:
            raise ValueError(
                "AI Code Review reviewer is missing required field: " + field_name
            )

    audit = payload.get("audit")
    if not isinstance(audit, dict):
        raise ValueError("AI Code Review audit block must be an object.")
    for field_name in [
        "candidate_content_hash",
        "reference_content_hash",
        "reviewer_output_hash",
        "evidence_verification",
    ]:
        if field_name not in audit:
            raise ValueError(
                "AI Code Review audit block is missing required field: " + field_name
            )

    return payload
