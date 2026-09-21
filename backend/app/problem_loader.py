import json
from pathlib import Path
from typing import Optional


LEGACY_SCHEMA = "legacy"
UNIVERSAL_SCHEMA = "universal"
UNIVERSAL_REQUIRED_FIELDS = (
    "schemaVersion",
    "id",
    "title",
    "description",
    "course",
    "sourcePlatform",
    "assignmentType",
    "evaluatorType",
    "language",
    "technologies",
    "instructions",
    "files",
    "submissionRules",
    "runtime",
    "promptPolicy",
    "tests",
    "scoring",
    "metadata",
)
UNIVERSAL_ALLOWED_FILE_ROLES = {
    "editable",
    "read_only",
    "test",
    "dependency",
    "runtime",
    "asset",
}


DEFAULT_PROBLEM_BANK = Path(__file__).resolve().parent.parent / "problem_bank"


def _is_safe_relative_path(path_value: str) -> bool:
    if not isinstance(path_value, str) or not path_value.strip():
        return False

    path = Path(path_value)

    if path.is_absolute():
        return False

    if "\\" in path_value:
        return False

    return all(part not in ("", ".", "..") for part in path.parts)


def _validate_reference_solution(
    definition: dict,
    source: Path,
    editable_files_by_path: dict,
) -> None:
    if "referenceSolution" not in definition:
        return

    reference_solution = definition["referenceSolution"]
    if not isinstance(reference_solution, dict):
        raise ValueError(f"{source.name} referenceSolution must be an object")

    source_name = reference_solution.get("source")
    if not isinstance(source_name, str) or not source_name.strip():
        raise ValueError(
            f"{source.name} referenceSolution.source must be a non-empty string"
        )

    files = reference_solution.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(
            f"{source.name} referenceSolution.files must be a non-empty list"
        )

    seen_paths = set()

    for file_definition in files:
        if not isinstance(file_definition, dict):
            raise ValueError(
                f"{source.name} referenceSolution contains an invalid file definition"
            )

        for field_name in ("path", "language", "content"):
            if field_name not in file_definition:
                raise ValueError(
                    f"{source.name} referenceSolution file is missing: {field_name}"
                )

        path_value = file_definition["path"]
        if not isinstance(path_value, str) or not _is_safe_relative_path(path_value):
            raise ValueError(
                f"{source.name} referenceSolution contains an unsafe file path"
            )

        if path_value in seen_paths:
            raise ValueError(
                f"{source.name} referenceSolution contains duplicate file paths"
            )
        seen_paths.add(path_value)

        editable_file_definition = editable_files_by_path.get(path_value)
        if editable_file_definition is None:
            raise ValueError(
                f"{source.name} referenceSolution path must match an editable file"
            )

        language = file_definition["language"]
        if not isinstance(language, str) or not language.strip():
            raise ValueError(
                f"{source.name} referenceSolution file language must be a non-empty string"
            )

        if language != editable_file_definition["language"]:
            raise ValueError(
                f"{source.name} referenceSolution language must match the editable file language"
            )

        content = file_definition["content"]
        if not isinstance(content, str):
            raise ValueError(
                f"{source.name} referenceSolution file content must be a string"
            )


def detect_problem_schema(definition: dict) -> str:
    if not isinstance(definition, dict):
        raise ValueError("Problem definition must be a JSON object")

    universal_marker_fields = (
        "schemaVersion",
        "assignmentType",
        "evaluatorType",
        "instructions",
        "submissionRules",
        "runtime",
        "promptPolicy",
    )
    files = definition.get("files")
    tests = definition.get("tests")

    is_universal = any(
        field_name in definition for field_name in universal_marker_fields
    )
    is_universal = is_universal or isinstance(tests, list)
    is_universal = is_universal or (
        isinstance(files, list)
        and any(
            isinstance(file_definition, dict)
            and ("path" in file_definition or "role" in file_definition)
            for file_definition in files
        )
    )

    is_legacy = "type" in definition or isinstance(tests, dict)
    is_legacy = is_legacy or (
        isinstance(files, list)
        and any(
            isinstance(file_definition, dict)
            and (
                "filename" in file_definition
                or "editable" in file_definition
                or "starter_content" in file_definition
            )
            for file_definition in files
        )
    )

    if is_universal:
        return UNIVERSAL_SCHEMA

    if is_legacy:
        return LEGACY_SCHEMA

    raise ValueError("Problem definition does not match a supported schema")


def validate_legacy_problem_definition(definition: dict, source: Path) -> None:
    required_fields = {
        "id": str,
        "title": str,
        "type": str,
        "language": str,
        "description": str,
        "files": list,
        "tests": dict,
        "metadata": dict,
    }

    for field_name, expected_type in required_fields.items():
        if field_name not in definition:
            raise ValueError(f"{source.name} is missing required field: {field_name}")
        if not isinstance(definition[field_name], expected_type):
            raise ValueError(f"{source.name} has an invalid {field_name} field")

    if not definition["id"].strip() or not definition["title"].strip():
        raise ValueError(f"{source.name} must have a non-empty id and title")

    if not definition["files"]:
        raise ValueError(f"{source.name} must define at least one file")

    for file_definition in definition["files"]:
        if not isinstance(file_definition, dict):
            raise ValueError(f"{source.name} contains an invalid file definition")
        for field_name in ("filename", "editable", "starter_content"):
            if field_name not in file_definition:
                raise ValueError(
                    f"{source.name} file definition is missing: {field_name}"
                )
        if not isinstance(file_definition["filename"], str):
            raise ValueError(f"{source.name} has an invalid file filename")
        if not isinstance(file_definition["editable"], bool):
            raise ValueError(f"{source.name} has an invalid file editable value")
        if not isinstance(file_definition["starter_content"], str):
            raise ValueError(f"{source.name} has invalid file starter_content")

    if not any(file_definition["editable"] for file_definition in definition["files"]):
        raise ValueError(f"{source.name} must define at least one editable file")

    _validate_reference_solution(
        definition,
        source,
        {
            file_definition["filename"]: {
                "language": definition["language"],
            }
            for file_definition in definition["files"]
            if file_definition["editable"]
        },
    )

    tests = definition["tests"]
    if not isinstance(tests.get("visible"), list) or not isinstance(
        tests.get("hidden"), list
    ):
        raise ValueError(f"{source.name} tests must include visible and hidden lists")

    if definition["type"] == "function" and not isinstance(
        definition.get("function_signature"), str
    ):
        raise ValueError(f"{source.name} function problem needs function_signature")

    if definition["type"] == "css_static_region":
        editable_region = definition.get("editable_region")
        checks = definition.get("checks")

        if not isinstance(editable_region, dict):
            raise ValueError(
                f"{source.name} css_static_region problem needs editable_region"
            )

        for field_name in ("file", "selector", "marker"):
            if not isinstance(editable_region.get(field_name), str):
                raise ValueError(
                    f"{source.name} editable_region is missing {field_name}"
                )

        if not isinstance(checks, dict):
            raise ValueError(f"{source.name} css_static_region problem needs checks")


def validate_universal_problem_definition(definition: dict, source: Path) -> None:
    for field_name in UNIVERSAL_REQUIRED_FIELDS:
        if field_name not in definition:
            raise ValueError(f"{source.name} is missing required field: {field_name}")

    for field_name in (
        "schemaVersion",
        "id",
        "title",
        "description",
        "course",
        "sourcePlatform",
        "assignmentType",
        "evaluatorType",
        "language",
    ):
        if not isinstance(definition[field_name], str) or not definition[field_name].strip():
            raise ValueError(f"{source.name} has an invalid {field_name} field")

    if not isinstance(definition["technologies"], list):
        raise ValueError(f"{source.name} has an invalid technologies field")

    instructions = definition["instructions"]
    if not isinstance(instructions, dict):
        raise ValueError(f"{source.name} instructions must be an object")
    student_prompt = instructions.get("studentPrompt")
    if not isinstance(student_prompt, str) or not student_prompt.strip():
        raise ValueError(
            f"{source.name} instructions.studentPrompt must be a non-empty string"
        )

    files = definition["files"]
    if not isinstance(files, list) or not files:
        raise ValueError(f"{source.name} files must be a non-empty list")

    editable_paths = []
    editable_files_by_path = {}

    for file_definition in files:
        if not isinstance(file_definition, dict):
            raise ValueError(f"{source.name} contains an invalid file definition")

        for field_name in (
            "path",
            "role",
            "language",
            "content",
            "includeInPrompt",
            "requiredInSubmission",
            "preserve",
        ):
            if field_name not in file_definition:
                raise ValueError(
                    f"{source.name} file definition is missing: {field_name}"
                )

        if not isinstance(file_definition["path"], str) or not _is_safe_relative_path(
            file_definition["path"]
        ):
            raise ValueError(f"{source.name} has an unsafe file path")

        if file_definition["role"] not in UNIVERSAL_ALLOWED_FILE_ROLES:
            raise ValueError(f"{source.name} has an invalid file role")

        if not isinstance(file_definition["language"], str):
            raise ValueError(f"{source.name} has an invalid file language")

        if file_definition["content"] is not None and not isinstance(
            file_definition["content"], str
        ):
            raise ValueError(f"{source.name} has an invalid file content value")

        for field_name in ("includeInPrompt", "requiredInSubmission", "preserve"):
            if not isinstance(file_definition[field_name], bool):
                raise ValueError(
                    f"{source.name} has an invalid file {field_name} value"
                )

        if "notes" in file_definition and file_definition["notes"] is not None and not isinstance(
            file_definition["notes"], str
        ):
            raise ValueError(f"{source.name} has invalid file notes")

        if file_definition["role"] == "editable":
            editable_paths.append(file_definition["path"])
            editable_files_by_path[file_definition["path"]] = {
                "language": file_definition["language"],
            }

    if not editable_paths:
        raise ValueError(f"{source.name} must define at least one editable file")

    _validate_reference_solution(definition, source, editable_files_by_path)

    submission_rules = definition["submissionRules"]
    if not isinstance(submission_rules, dict):
        raise ValueError(f"{source.name} submissionRules must be an object")

    if submission_rules.get("mode") != "full_editable_file":
        raise ValueError(
            f"{source.name} submissionRules.mode must equal full_editable_file"
        )

    configured_editable_paths = submission_rules.get("editablePaths")
    if not isinstance(configured_editable_paths, list) or not configured_editable_paths:
        raise ValueError(
            f"{source.name} submissionRules.editablePaths must be a non-empty list"
        )

    for editable_path in configured_editable_paths:
        if not isinstance(editable_path, str) or not _is_safe_relative_path(editable_path):
            raise ValueError(
                f"{source.name} submissionRules contains an unsafe editable path"
            )
        if editable_path not in editable_paths:
            raise ValueError(
                f"{source.name} submissionRules.editablePaths must match editable files"
            )

    runtime = definition["runtime"]
    if not isinstance(runtime, dict):
        raise ValueError(f"{source.name} runtime must be an object")

    prompt_policy = definition["promptPolicy"]
    if not isinstance(prompt_policy, dict):
        raise ValueError(f"{source.name} promptPolicy must be an object")
    if prompt_policy.get("showTests") is not False:
        raise ValueError(f"{source.name} promptPolicy.showTests must be false")
    if prompt_policy.get("showPointValues") is not False:
        raise ValueError(f"{source.name} promptPolicy.showPointValues must be false")
    if prompt_policy.get("showEvaluatorType") is not False:
        raise ValueError(f"{source.name} promptPolicy.showEvaluatorType must be false")

    tests = definition["tests"]
    if not isinstance(tests, list) or not tests:
        raise ValueError(f"{source.name} tests must be a non-empty list")

    seen_test_ids = set()
    total_points = 0

    for test_definition in tests:
        if not isinstance(test_definition, dict):
            raise ValueError(f"{source.name} contains an invalid test definition")

        for field_name in (
            "id",
            "name",
            "framework",
            "path",
            "source",
            "points",
            "visibility",
            "timeoutMs",
            "isolation",
            "async",
            "mutatesGlobals",
        ):
            if field_name not in test_definition:
                raise ValueError(
                    f"{source.name} test definition is missing: {field_name}"
                )

        test_id = test_definition["id"]
        if not isinstance(test_id, str) or not test_id.strip():
            raise ValueError(f"{source.name} has an invalid test id")
        if test_id in seen_test_ids:
            raise ValueError(f"{source.name} contains duplicate test ids")
        seen_test_ids.add(test_id)

        if not isinstance(test_definition["source"], str) or not test_definition[
            "source"
        ].strip():
            raise ValueError(f"{source.name} test source must be non-empty")

        if not isinstance(test_definition["path"], str) or not _is_safe_relative_path(
            test_definition["path"]
        ):
            raise ValueError(f"{source.name} has an unsafe test path")

        points = test_definition["points"]
        if not isinstance(points, (int, float)) or isinstance(points, bool) or points <= 0:
            raise ValueError(f"{source.name} test points must be greater than zero")

        if test_definition["visibility"] != "hidden":
            raise ValueError(f"{source.name} test visibility must equal hidden")

        for field_name in ("name", "framework", "isolation"):
            if not isinstance(test_definition[field_name], str) or not test_definition[
                field_name
            ].strip():
                raise ValueError(f"{source.name} has an invalid test {field_name}")

        if not isinstance(test_definition["timeoutMs"], int) or test_definition[
            "timeoutMs"
        ] <= 0:
            raise ValueError(f"{source.name} test timeoutMs must be a positive integer")

        for field_name in ("async", "mutatesGlobals"):
            if not isinstance(test_definition[field_name], bool):
                raise ValueError(f"{source.name} has an invalid test {field_name}")

        total_points += points

    scoring = definition["scoring"]
    if not isinstance(scoring, dict):
        raise ValueError(f"{source.name} scoring must be an object")
    if scoring.get("mode") != "test_all_or_nothing":
        raise ValueError(f"{source.name} scoring.mode must equal test_all_or_nothing")
    if scoring.get("activationStatus") not in {"ready", "incomplete"}:
        raise ValueError(
            f"{source.name} scoring.activationStatus must be ready or incomplete"
        )
    if scoring.get("maximumPoints") != total_points:
        raise ValueError(
            f"{source.name} scoring.maximumPoints must equal the sum of test points"
        )

    if "mocks" in definition and not isinstance(definition["mocks"], dict):
        raise ValueError(f"{source.name} mocks must be an object when provided")


def validate_problem_definition(definition: dict, source: Path) -> None:
    schema = detect_problem_schema(definition)

    if schema == LEGACY_SCHEMA:
        validate_legacy_problem_definition(definition, source)
        return

    validate_universal_problem_definition(definition, source)


def load_problem_definition(problem_file: Path) -> dict:
    """Load and validate one problem JSON file."""
    try:
        definition = json.loads(problem_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {problem_file.name}: {error}") from error

    if not isinstance(definition, dict):
        raise ValueError(f"{problem_file.name} must contain a JSON object")

    validate_problem_definition(definition, problem_file)
    return definition


def load_problem_definitions(
    problem_bank_path: Optional[Path] = None,
) -> list[dict]:
    """Load and minimally validate every JSON problem in the problem bank."""
    bank_path = problem_bank_path or DEFAULT_PROBLEM_BANK

    if not bank_path.exists():
        raise ValueError(f"Problem bank directory does not exist: {bank_path}")

    definitions = []

    for problem_file in sorted(bank_path.glob("*.json")):
        definitions.append(load_problem_definition(problem_file))

    return definitions
