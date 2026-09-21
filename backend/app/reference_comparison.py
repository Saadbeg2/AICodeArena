from difflib import SequenceMatcher, unified_diff
from typing import Optional


SUPPORTED_REFERENCE_LANGUAGES = {"html", "css", "javascript", "pug"}


def normalize_reference_content(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized_lines = [line.rstrip() for line in normalized.split("\n")]
    normalized = "\n".join(normalized_lines)
    return normalized.rstrip("\n")


def _line_diff_counts(reference_text: str, submitted_text: str) -> dict:
    reference_lines = reference_text.split("\n")
    submitted_lines = submitted_text.split("\n")
    matcher = SequenceMatcher(None, reference_lines, submitted_lines)

    added = 0
    removed = 0
    changed = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            removed += i2 - i1
            added += j2 - j1
            changed += max(i2 - i1, j2 - j1)

    return {
        "added_line_count": added,
        "removed_line_count": removed,
        "changed_line_count": changed,
    }


def _build_file_comparison(
    path: str,
    language: Optional[str],
    reference_content: str,
    submitted_content: str,
) -> dict:
    normalized_reference = normalize_reference_content(reference_content)
    normalized_submitted = normalize_reference_content(submitted_content)
    exact_match = reference_content == submitted_content
    normalized_match = normalized_reference == normalized_submitted
    diff_counts = _line_diff_counts(normalized_reference, normalized_submitted)
    diff_lines = list(
        unified_diff(
            normalized_reference.split("\n"),
            normalized_submitted.split("\n"),
            fromfile=f"reference/{path}",
            tofile=f"submission/{path}",
            lineterm="",
        )
    )

    return {
        "path": path,
        "language": language,
        "exact_match": exact_match,
        "normalized_match": normalized_match,
        **diff_counts,
        "unified_diff": diff_lines,
    }


def compare_submitted_files_to_reference(
    problem_definition: dict,
    submitted_files: dict,
) -> dict:
    reference_solution = problem_definition.get("referenceSolution")

    if not reference_solution:
        return {
            "reference_available": False,
            "compared_file_paths": [],
            "missing_submitted_files": [],
            "unexpected_submitted_files": sorted(submitted_files.keys()),
            "files": [],
            "overall_exact_match": False,
            "overall_normalized_match": False,
        }

    reference_files = reference_solution.get("files", [])
    reference_by_path = {
        file_definition["path"]: file_definition for file_definition in reference_files
    }
    submitted_paths = set(submitted_files.keys())
    reference_paths = set(reference_by_path.keys())

    missing_submitted_files = sorted(reference_paths - submitted_paths)
    unexpected_submitted_files = sorted(submitted_paths - reference_paths)
    compared_paths = sorted(reference_paths & submitted_paths)
    file_results = []

    for path in compared_paths:
        reference_file = reference_by_path[path]
        file_results.append(
            _build_file_comparison(
                path,
                reference_file.get("language"),
                reference_file["content"],
                submitted_files[path],
            )
        )

    overall_exact_match = (
        not missing_submitted_files
        and not unexpected_submitted_files
        and bool(file_results)
        and all(file_result["exact_match"] for file_result in file_results)
    )
    overall_normalized_match = (
        not missing_submitted_files
        and not unexpected_submitted_files
        and bool(file_results)
        and all(file_result["normalized_match"] for file_result in file_results)
    )

    return {
        "reference_available": True,
        "reference_source": reference_solution.get("source"),
        "compared_file_paths": compared_paths,
        "missing_submitted_files": missing_submitted_files,
        "unexpected_submitted_files": unexpected_submitted_files,
        "files": file_results,
        "overall_exact_match": overall_exact_match,
        "overall_normalized_match": overall_normalized_match,
    }


def build_submitted_editable_files(
    problem_definition: dict,
    submitted_code: str,
) -> dict:
    submission_rules = problem_definition.get("submissionRules", {})
    editable_paths = submission_rules.get("editablePaths", [])

    if submission_rules.get("mode") != "full_editable_file" or len(editable_paths) != 1:
        raise ValueError(
            "Reference comparison currently supports full_editable_file submissions "
            "with exactly one editable file."
        )

    editable_path = editable_paths[0]
    file_definitions = {
        file_definition["path"]: file_definition
        for file_definition in problem_definition.get("files", [])
    }
    editable_file = file_definitions.get(editable_path, {})
    language = str(editable_file.get("language", "")).lower()

    if language not in SUPPORTED_REFERENCE_LANGUAGES:
        raise ValueError(
            "Reference comparison currently supports HTML, CSS, JavaScript, and Pug."
        )

    return {editable_path: submitted_code}
