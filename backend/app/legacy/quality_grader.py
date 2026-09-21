from __future__ import annotations

"""
Legacy deterministic quality grader.

This module is no longer active in the AICodeArena scoring pipeline.
It was replaced because its rubric was too coarse for the current demo goals.
It remains here for historical reference and possible future comparison only.
"""

from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
import math
import re
from typing import Any, Dict, Optional

from app.reference_comparison import normalize_reference_content


FUNCTIONAL_GATE_REASON = "Functional tests must pass before quality grading."
REFERENCE_REQUIRED_REASON = "Quality grading requires a reference solution."
UNSUPPORTED_QUALITY_REASON = (
    "Quality grading is currently available only for universal reference-backed submissions."
)

CONCISENESS_POINTS = 40.0
STRUCTURAL_POINTS = 30.0
REFERENCE_SIMILARITY_POINTS = 20.0
VALIDATION_CLEANLINESS_POINTS = 10.0


def _round_score(value: float) -> float:
    return round(float(value), 2)


def _nonblank_line_count(content: str) -> int:
    normalized = normalize_reference_content(content)
    return sum(1 for line in normalized.split("\n") if line.strip())


def _is_functionally_perfect(execution_result: dict) -> bool:
    earned = execution_result.get("score_earned")
    possible = execution_result.get("score_possible")
    if earned is None or possible is None:
        return False
    try:
        return math.isclose(float(earned), float(possible), rel_tol=0.0, abs_tol=1e-9)
    except (TypeError, ValueError):
        return False


class _TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self.tags.append(tag.lower())
        for name, value in attrs:
            if name.lower() == "id" and value:
                self.ids.append(value)


@dataclass
class StructuralMetrics:
    score: float
    details: Dict[str, Any]
    explanation: str
    status: str = "evaluated"


def _duplicate_count(values: list[str]) -> int:
    counts = Counter(values)
    return sum(count - 1 for count in counts.values() if count > 1)


def _html_or_pug_structure_metrics(
    candidate_content: str,
    reference_content: str,
    language: str,
) -> StructuralMetrics:
    if language == "html":
        candidate_parser = _TagCollector()
        reference_parser = _TagCollector()
        candidate_parser.feed(candidate_content)
        reference_parser.feed(reference_content)
        candidate_tags = candidate_parser.tags
        reference_tags = reference_parser.tags
        candidate_ids = candidate_parser.ids
    else:
        tag_pattern = re.compile(r"^\s*([a-zA-Z][\w-]*)")
        id_pattern = re.compile(r"#([A-Za-z_][\w-]*)")
        candidate_tags = []
        reference_tags = []
        candidate_ids = []
        for line in candidate_content.splitlines():
            tag_match = tag_pattern.match(line)
            if tag_match:
                candidate_tags.append(tag_match.group(1).lower())
            candidate_ids.extend(id_pattern.findall(line))
        for line in reference_content.splitlines():
            tag_match = tag_pattern.match(line)
            if tag_match:
                reference_tags.append(tag_match.group(1).lower())

    candidate_counts = Counter(candidate_tags)
    reference_counts = Counter(reference_tags)
    duplicate_ids = _duplicate_count(candidate_ids)
    required_controls = ["form", "button", "input", "select", "textarea", "fieldset"]
    wrapper_tags = ["div", "section", "article", "main", "span"]

    duplicate_required_controls = sum(
        max(candidate_counts[tag] - reference_counts[tag], 0)
        for tag in required_controls
    )
    extra_wrappers = sum(
        max(candidate_counts[tag] - reference_counts[tag], 0)
        for tag in wrapper_tags
    )
    extra_elements = max(len(candidate_tags) - len(reference_tags), 0)

    penalty = min(
        STRUCTURAL_POINTS,
        duplicate_ids * 3.0
        + duplicate_required_controls * 2.0
        + extra_wrappers * 0.75
        + max(extra_elements - extra_wrappers, 0) * 0.5,
    )
    earned = _round_score(max(0.0, STRUCTURAL_POINTS - penalty))

    explanation_parts = []
    if duplicate_ids:
        explanation_parts.append(f"{duplicate_ids} duplicate id(s)")
    if duplicate_required_controls:
        explanation_parts.append(
            f"{duplicate_required_controls} duplicate required control(s)"
        )
    if extra_wrappers:
        explanation_parts.append(f"{extra_wrappers} extra wrapper element(s)")
    if not explanation_parts:
        explanation = "The submission structure closely matches the required layout."
    else:
        explanation = "Structural deductions were applied for " + ", ".join(
            explanation_parts
        ) + "."

    return StructuralMetrics(
        score=earned,
        details={
            "extra_elements": extra_elements,
            "duplicate_ids": duplicate_ids,
            "duplicate_required_controls": duplicate_required_controls,
            "extra_wrappers": extra_wrappers,
        },
        explanation=explanation,
    )


def _parse_css_rules(content: str) -> list[tuple[str, list[tuple[str, str]]]]:
    rules = []
    for selector, block in re.findall(r"([^{}]+)\{([^{}]*)\}", content, flags=re.S):
        selector_name = " ".join(selector.split()).strip()
        declarations = []
        for raw_declaration in block.split(";"):
            if ":" not in raw_declaration:
                continue
            property_name, value = raw_declaration.split(":", 1)
            declarations.append((property_name.strip().lower(), value.strip()))
        if selector_name:
            rules.append((selector_name, declarations))
    return rules


def _css_structure_metrics(
    candidate_content: str,
    reference_content: str,
) -> StructuralMetrics:
    candidate_rules = _parse_css_rules(candidate_content)
    reference_rules = _parse_css_rules(reference_content)
    candidate_selectors = [selector for selector, _ in candidate_rules]
    reference_selector_counts = Counter(selector for selector, _ in reference_rules)
    extra_selectors = sum(
        1
        for selector in candidate_selectors
        if reference_selector_counts[selector] == 0
    )

    duplicate_declarations = 0
    conflicting_declarations = 0
    for _selector, declarations in candidate_rules:
        property_values: Dict[str, set[str]] = {}
        for property_name, value in declarations:
            property_values.setdefault(property_name, set()).add(value)
        for values in property_values.values():
            if len(values) > 1:
                conflicting_declarations += 1
        duplicate_declarations += max(
            len(declarations) - len(property_values),
            0,
        )

    penalty = min(
        STRUCTURAL_POINTS,
        extra_selectors * 1.5
        + duplicate_declarations * 1.0
        + conflicting_declarations * 2.0,
    )
    earned = _round_score(max(0.0, STRUCTURAL_POINTS - penalty))

    explanation_parts = []
    if extra_selectors:
        explanation_parts.append(f"{extra_selectors} unnecessary selector(s)")
    if duplicate_declarations:
        explanation_parts.append(
            f"{duplicate_declarations} duplicate declaration(s)"
        )
    if conflicting_declarations:
        explanation_parts.append(
            f"{conflicting_declarations} conflicting declaration(s)"
        )
    if not explanation_parts:
        explanation = "The stylesheet structure stays focused on the required selectors."
    else:
        explanation = "Structural deductions were applied for " + ", ".join(
            explanation_parts
        ) + "."

    return StructuralMetrics(
        score=earned,
        details={
            "unnecessary_selectors": extra_selectors,
            "duplicate_declarations": duplicate_declarations,
            "conflicting_declarations": conflicting_declarations,
        },
        explanation=explanation,
    )


def _javascript_structure_metrics(
    candidate_content: str,
    reference_content: str,
) -> StructuralMetrics:
    function_pattern = re.compile(r"function\s+([A-Za-z_][\w]*)\s*\(")
    top_level_var_pattern = re.compile(
        r"^\s*(?:var|let|const)\s+([A-Za-z_][\w]*)",
        flags=re.M,
    )
    window_global_pattern = re.compile(r"window\.([A-Za-z_][\w]*)\s*=")

    candidate_functions = function_pattern.findall(candidate_content)
    reference_functions = function_pattern.findall(reference_content)
    duplicate_logic = _duplicate_count(candidate_functions)
    unnecessary_globals = max(
        len(top_level_var_pattern.findall(candidate_content))
        + len(window_global_pattern.findall(candidate_content))
        - len(top_level_var_pattern.findall(reference_content))
        - len(window_global_pattern.findall(reference_content)),
        0,
    )
    unreachable_code = len(
        re.findall(r"return\b[^\n]*\n\s*[A-Za-z_$]", candidate_content)
    )

    penalty = min(
        STRUCTURAL_POINTS,
        duplicate_logic * 4.0 + unnecessary_globals * 2.0 + unreachable_code * 1.5,
    )
    earned = _round_score(max(0.0, STRUCTURAL_POINTS - penalty))

    explanation_parts = []
    if duplicate_logic:
        explanation_parts.append(f"{duplicate_logic} duplicate function definition(s)")
    if unnecessary_globals:
        explanation_parts.append(f"{unnecessary_globals} unnecessary global(s)")
    if unreachable_code:
        explanation_parts.append(f"{unreachable_code} unreachable code block(s)")
    if not explanation_parts:
        explanation = "The JavaScript stays close to the required structure."
    else:
        explanation = "Structural deductions were applied for " + ", ".join(
            explanation_parts
        ) + "."

    return StructuralMetrics(
        score=earned,
        details={
            "duplicate_logic": duplicate_logic,
            "unnecessary_globals": unnecessary_globals,
            "unreachable_code_blocks": unreachable_code,
        },
        explanation=explanation,
    )


def _unavailable_structural_metrics(language: str) -> StructuralMetrics:
    return StructuralMetrics(
        score=STRUCTURAL_POINTS,
        details={
            "unavailable_checks": [
                f"No structural heuristics are currently defined for {language}."
            ]
        },
        explanation="Structural heuristics are unavailable for this language, so no structural deduction was applied.",
        status="unavailable",
    )


def _build_conciseness_breakdown(
    reference_files: list[dict],
    submitted_files: dict[str, str],
) -> dict:
    reference_nonblank_lines = sum(
        _nonblank_line_count(file_definition.get("content", ""))
        for file_definition in reference_files
    )
    candidate_nonblank_lines = sum(
        _nonblank_line_count(content)
        for content in submitted_files.values()
    )
    excess_lines = max(candidate_nonblank_lines - reference_nonblank_lines, 0)
    denominator = max(reference_nonblank_lines, 1)
    excess_ratio = excess_lines / denominator
    penalty_ratio = min(excess_ratio, 1.0)
    earned = _round_score(CONCISENESS_POINTS * (1.0 - penalty_ratio))

    if excess_lines == 0:
        explanation = "The submission is no longer than the reference on a nonblank-line basis."
    else:
        explanation = (
            f"The solution contains {excess_lines} more nonblank lines than the reference."
        )

    return {
        "earned": earned,
        "possible": CONCISENESS_POINTS,
        "status": "evaluated",
        "details": {
            "reference_nonblank_lines": reference_nonblank_lines,
            "candidate_nonblank_lines": candidate_nonblank_lines,
            "excess_lines": excess_lines,
            "excess_ratio": round(excess_ratio, 4),
        },
        "explanation": explanation,
    }


def _build_reference_similarity_breakdown(comparison_result: dict) -> dict:
    files = comparison_result.get("files", []) or []
    added_line_count = sum(file_result.get("added_line_count", 0) or 0 for file_result in files)
    removed_line_count = sum(file_result.get("removed_line_count", 0) or 0 for file_result in files)
    changed_line_count = sum(file_result.get("changed_line_count", 0) or 0 for file_result in files)
    diff_units = added_line_count + removed_line_count + changed_line_count
    reference_line_baseline = max(
        added_line_count + removed_line_count + changed_line_count,
        1,
    )
    if comparison_result.get("overall_normalized_match"):
        earned = REFERENCE_SIMILARITY_POINTS
    else:
        diff_ratio = min(diff_units / (reference_line_baseline * 2.0), 1.0)
        earned = _round_score(
            REFERENCE_SIMILARITY_POINTS * max(0.6, 1.0 - (diff_ratio * 0.4))
        )

    explanation = (
        "The submission matches the reference after normalization."
        if comparison_result.get("overall_normalized_match")
        else "The solution differs from the reference but remains comparable after normalization."
    )

    return {
        "earned": earned,
        "possible": REFERENCE_SIMILARITY_POINTS,
        "status": "evaluated",
        "details": {
            "exact_match": bool(comparison_result.get("overall_exact_match")),
            "normalized_match": bool(comparison_result.get("overall_normalized_match")),
            "added_line_count": added_line_count,
            "removed_line_count": removed_line_count,
            "changed_line_count": changed_line_count,
        },
        "explanation": explanation,
    }


def _build_validation_cleanliness_breakdown(
    language: str,
    execution_result: dict,
    structural_details: dict,
) -> dict:
    warnings = 0
    test_results = execution_result.get("test_results", []) or []
    for test_result in test_results:
        warnings += len(test_result.get("console_errors", []) or [])
        warnings += len(test_result.get("page_errors", []) or [])

    duplicate_ids = int(structural_details.get("duplicate_ids", 0) or 0)
    syntax_valid = execution_result.get("status") != "FORMAT_ERROR"
    malformed_structure = False

    penalty = min(
        VALIDATION_CLEANLINESS_POINTS,
        (0.0 if syntax_valid else VALIDATION_CLEANLINESS_POINTS)
        + warnings * 0.5
        + duplicate_ids * 0.5,
    )
    earned = _round_score(max(0.0, VALIDATION_CLEANLINESS_POINTS - penalty))

    if warnings == 0 and duplicate_ids == 0 and syntax_valid:
        explanation = "The submission is valid and did not produce warnings."
    else:
        explanation = (
            "The submission is valid but produced "
            f"{warnings} warning(s) and {duplicate_ids} duplicate id issue(s)."
        )

    return {
        "earned": earned,
        "possible": VALIDATION_CLEANLINESS_POINTS,
        "status": "evaluated",
        "details": {
            "syntax_valid": syntax_valid,
            "duplicate_ids": duplicate_ids,
            "warnings": warnings,
            "malformed_structure": malformed_structure,
            "language": language,
        },
        "explanation": explanation,
    }


def _determine_language(reference_files: list[dict], submitted_files: dict[str, str]) -> str:
    if reference_files:
        return str(reference_files[0].get("language", "")).lower()
    if submitted_files:
        first_path = next(iter(submitted_files))
        if first_path.endswith(".html"):
            return "html"
        if first_path.endswith(".css"):
            return "css"
        if first_path.endswith(".js"):
            return "javascript"
        if first_path.endswith(".pug"):
            return "pug"
    return ""


def _build_structural_breakdown(
    language: str,
    reference_files: list[dict],
    submitted_files: dict[str, str],
) -> dict:
    reference_content = "\n".join(
        file_definition.get("content", "") for file_definition in reference_files
    )
    submitted_content = "\n".join(submitted_files.values())

    if language in {"html", "pug"}:
        metrics = _html_or_pug_structure_metrics(
            submitted_content,
            reference_content,
            language,
        )
    elif language == "css":
        metrics = _css_structure_metrics(submitted_content, reference_content)
    elif language == "javascript":
        metrics = _javascript_structure_metrics(submitted_content, reference_content)
    else:
        metrics = _unavailable_structural_metrics(language or "unknown")

    return {
        "earned": metrics.score,
        "possible": STRUCTURAL_POINTS,
        "status": metrics.status,
        "details": metrics.details,
        "explanation": metrics.explanation,
    }


def build_not_evaluated_quality_result(
    functional_percentage: Optional[float],
    reason: str,
) -> dict:
    return {
        "quality_status": "not_evaluated",
        "quality_score": None,
        "competition_score": functional_percentage,
        "quality_breakdown": None,
        "quality_reason": reason,
    }


def evaluate_solution_quality(
    problem_definition: Optional[dict],
    submitted_files: Optional[dict[str, str]],
    execution_result: dict,
    comparison_result: Optional[dict],
) -> dict:
    functional_percentage = execution_result.get("score_percentage")

    if not _is_functionally_perfect(execution_result):
        return build_not_evaluated_quality_result(
            functional_percentage,
            FUNCTIONAL_GATE_REASON,
        )

    if not problem_definition or not submitted_files:
        return build_not_evaluated_quality_result(
            functional_percentage,
            UNSUPPORTED_QUALITY_REASON,
        )

    reference_solution = problem_definition.get("referenceSolution") or {}
    reference_files = reference_solution.get("files", []) or []
    if not reference_files or not comparison_result or not comparison_result.get(
        "reference_available"
    ):
        return build_not_evaluated_quality_result(
            functional_percentage,
            REFERENCE_REQUIRED_REASON,
        )

    language = _determine_language(reference_files, submitted_files)
    conciseness = _build_conciseness_breakdown(reference_files, submitted_files)
    structural_precision = _build_structural_breakdown(
        language,
        reference_files,
        submitted_files,
    )
    reference_similarity = _build_reference_similarity_breakdown(comparison_result)
    validation_cleanliness = _build_validation_cleanliness_breakdown(
        language,
        execution_result,
        structural_precision.get("details", {}),
    )

    quality_score = _round_score(
        conciseness["earned"]
        + structural_precision["earned"]
        + reference_similarity["earned"]
        + validation_cleanliness["earned"]
    )
    competition_score = _round_score(90.0 + (quality_score * 0.10))

    return {
        "quality_status": "evaluated",
        "quality_score": quality_score,
        "competition_score": competition_score,
        "quality_breakdown": {
            "conciseness": conciseness,
            "structural_precision": structural_precision,
            "reference_similarity": reference_similarity,
            "validation_cleanliness": validation_cleanliness,
        },
        "quality_reason": None,
    }
