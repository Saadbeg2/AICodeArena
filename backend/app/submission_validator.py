import ast
from dataclasses import dataclass
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional

from app.models import Problem
from app.node_jest_pug_evaluator import (
    NODE_EVALUATOR_TYPE,
    compile_pug_submission,
)
from app.problem_loader import UNIVERSAL_SCHEMA, detect_problem_schema


# Language labels that AI models sometimes place above code, such as:
#
# python
# def add(a, b):
#     return a + b
#
# In official scoring, this should be rejected because the model was asked to
# return raw executable code only, not a language label plus code.
LANGUAGE_TAGS = {
    "c",
    "cpp",
    "csharp",
    "go",
    "java",
    "javascript",
    "js",
    "python",
    "py",
    "ruby",
    "rust",
    "typescript",
    "ts",
}


# Detect Markdown code fences, such as:
#
# ```python
# def add(a, b):
#     return a + b
# ```
#
# Even if the code inside is correct, official scoring rejects this because the
# model did not follow the output format requirement.
TRIPLE_BACKTICK_PATTERN = re.compile(r"```")
HTML_DOCTYPE_PATTERN = re.compile(r"^\s*<!DOCTYPE\s+html>\s*", re.IGNORECASE)
HTML_TAG_PATTERN = re.compile(r"<(/?)([a-zA-Z0-9]+)\b[^>]*>")
FILENAME_HEADING_PATTERN = re.compile(
    r"^\s*[A-Za-z0-9_./\\-]+\.(html|css|js|jsx|py|ts|tsx|pug)\s*:?\s*$",
    re.IGNORECASE,
)
COMMON_PROSE_PREFIXES = (
    "here is",
    "here's",
    "the solution",
    "solution:",
    "explanation:",
    "i would",
    "i will",
    "this file",
)
JAVASCRIPT_LANGUAGE_TAGS = {"javascript", "js"}
CSS_LANGUAGE_TAGS = {"css"}
PUG_LANGUAGE_TAGS = {"pug"}


@dataclass
class ValidationResult:
    # True means the response is acceptable raw Python code and can be sent to
    # the test harness.
    is_valid: bool

    # If valid, this contains the exact code that should be executed.
    # If invalid, this stays None so invalid output is not accidentally tested.
    code: Optional[str]

    # If invalid, this explains why the model response failed validation.
    # If valid, this is None.
    error_message: Optional[str]


def _format_error(message: str) -> ValidationResult:
    """Build a consistent failed validation result."""
    return ValidationResult(
        is_valid=False,
        code=None,
        error_message=message,
    )


def _success(code: str) -> ValidationResult:
    return ValidationResult(
        is_valid=True,
        code=code,
        error_message=None,
    )


def _first_non_empty_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _looks_like_filename_heading(line: str) -> bool:
    return bool(FILENAME_HEADING_PATTERN.match(line))


def _has_balanced_braces(text: str) -> bool:
    brace_count = 0

    for character in text:
        if character == "{":
            brace_count += 1
        elif character == "}":
            brace_count -= 1
            if brace_count < 0:
                return False

    return brace_count == 0


def _shared_full_file_checks(
    raw_response: str,
    expected_kind: str,
    allowed_language_tags: set,
) -> Optional[ValidationResult]:
    stripped_response = raw_response.strip()

    if not stripped_response:
        return _format_error(
            "Model output was empty. Expected the complete file contents only."
        )

    if TRIPLE_BACKTICK_PATTERN.search(stripped_response):
        return _format_error(
            "Model output included Markdown fences or non-code text. "
            "Expected the complete file contents only."
        )

    first_non_empty_line = _first_non_empty_line(stripped_response)
    lowered_first_line = first_non_empty_line.lower()

    if lowered_first_line in allowed_language_tags or lowered_first_line in LANGUAGE_TAGS:
        return _format_error(
            "Model output included a standalone language label. "
            "Expected the complete file contents only."
        )

    if _looks_like_filename_heading(first_non_empty_line):
        return _format_error(
            "Model output included a filename heading. "
            "Expected the complete file contents only."
        )

    if lowered_first_line.startswith(COMMON_PROSE_PREFIXES):
        return _format_error(
            "Model output included explanatory prose. "
            "Expected the complete file contents only."
        )

    if "```" in raw_response:
        return _format_error(
            "Model output included Markdown fences or non-code text. "
            "Expected the complete file contents only."
        )

    if expected_kind == "html" and "<html" not in stripped_response.lower():
        return _format_error(
            "Model output does not resemble a complete HTML file."
        )

    if expected_kind == "css" and stripped_response.count("{") == 0:
        return _format_error(
            "Model output does not resemble a complete CSS file."
        )

    if expected_kind == "javascript":
        if lowered_first_line.endswith(".js") or lowered_first_line.endswith(".javascript"):
            return _format_error(
                "Model output included a filename heading. "
                "Expected the complete file contents only."
            )
        if lowered_first_line.startswith("<") or stripped_response.lstrip().lower().startswith(
            "<!doctype"
        ):
            return _format_error(
                "Model output included non-JavaScript content. "
                "Expected the complete file contents only."
            )

    return None


def _validate_javascript_syntax_with_node(source_code: str) -> Optional[ValidationResult]:
    node_path = shutil.which("node")

    if node_path is None:
        return None

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".js",
            delete=False,
            encoding="utf-8",
        ) as temporary_file:
            temporary_file.write(source_code)
            temporary_path = temporary_file.name

        completed_process = subprocess.run(
            [node_path, "--check", temporary_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)

    if completed_process.returncode != 0:
        stderr = (completed_process.stderr or "").strip()
        return _format_error(
            "Model output included invalid JavaScript syntax. "
            + (stderr if stderr else "Expected a complete JavaScript file.")
        )

    return _success(source_code)


def validate_raw_code_submission(raw_response: str) -> ValidationResult:
    """
    Validate that a model returned raw executable Python code only.

    Accepted example:
        def add(a, b):
            return a + b

    Also accepted:
        # This function adds two numbers.
        def add(a, b):
            return a + b

    Rejected example:
        ```python
        def add(a, b):
            return a + b
        ```

    Rejected example:
        python
        def add(a, b):
            return a + b

    Rejected example:
        Here is the solution:
        def add(a, b):
            return a + b
    """
    # Leading/trailing blank lines do not change the submitted code, so they are
    # trimmed before validation and execution.
    stripped_response = raw_response.strip()

    # Empty output cannot be scored because the model did not submit code.
    if not stripped_response:
        return _format_error("Model output was empty. Expected raw executable code only.")

    # Reject Markdown fences instead of extracting the code from them.
    # This keeps scoring strict: the benchmark should not repair model output.
    if TRIPLE_BACKTICK_PATTERN.search(stripped_response):
        return _format_error(
            "Model output included Markdown fences or non-code text. "
            "Expected raw executable code only."
        )

    lines = stripped_response.splitlines()

    # Find the first real line so blank lines at the top do not hide a language tag.
    # Example rejected:
    #
    # python
    # def add(a, b):
    #     return a + b
    first_non_empty_line = next(
        (line.strip() for line in lines if line.strip()),
        "",
    ).lower()

    # Reject standalone language labels like "python" or "js".
    # The model should return the code itself, not a label describing the code.
    if first_non_empty_line in LANGUAGE_TAGS:
        return _format_error(
            "Model output included a standalone language label. "
            "Expected raw executable code only."
        )

    try:
        # ast.parse checks whether the entire response is valid Python syntax.
        #
        # Accepted:
        # def add(a, b):
        #     return a + b
        #
        # Accepted:
        # # This function adds two numbers.
        # def add(a, b):
        #     return a + b
        #
        # Rejected:
        # Here is the solution:
        # def add(a, b):
        #     return a + b
        tree = ast.parse(stripped_response)
    except SyntaxError:
        return _format_error(
            "Model output included non-code text or invalid Python syntax. "
            "Expected raw executable code only."
        )

    # ast.parse accepts top-level string literals because Python treats them as
    # valid expressions/docstrings. For this benchmark, top-level explanatory
    # strings are rejected because they are not needed raw code.
    #
    # Rejected:
    # "This function adds two numbers."
    #
    # def add(a, b):
    #     return a + b
    #
    # Still accepted:
    # def add(a, b):
    #     "Return the sum of two numbers."
    #     return a + b
    #
    # Still accepted:
    # # This function adds two numbers.
    # def add(a, b):
    #     return a + b
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return _format_error(
                "Model output included explanatory text. "
                "Expected raw executable code only."
            )

    # If validation passes, the exact submitted code is returned for the test
    # harness. No Markdown cleanup or rescue step is performed.
    return _success(stripped_response)


def validate_css_declaration_submission(raw_response: str) -> ValidationResult:
    """Validate that a model returned raw CSS declarations only."""
    stripped_response = raw_response.strip()

    if not stripped_response:
        return _format_error("Model output was empty. Expected raw CSS declarations only.")

    if TRIPLE_BACKTICK_PATTERN.search(stripped_response):
        return _format_error(
            "Model output included Markdown fences or non-code text. "
            "Expected raw CSS declarations only."
        )

    lines = stripped_response.splitlines()
    first_non_empty_line = next(
        (line.strip() for line in lines if line.strip()),
        "",
    ).lower()

    if first_non_empty_line in LANGUAGE_TAGS or first_non_empty_line == "css":
        return _format_error(
            "Model output included a standalone language label. "
            "Expected raw CSS declarations only."
        )

    if "{" in stripped_response or "}" in stripped_response:
        return _format_error(
            "Model output included selector wrappers or a full file. "
            "Expected only raw CSS declarations for the TODO region."
        )

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line or (
            stripped_line.startswith("/*") and stripped_line.endswith("*/")
        ):
            continue
        if ":" not in stripped_line or not stripped_line.endswith(";"):
            return _format_error(
                "Model output included non-declaration text. "
                "Expected only raw CSS declarations."
            )

    return _success(stripped_response)


def validate_html_full_file_submission(raw_response: str) -> ValidationResult:
    stripped_response = raw_response.strip()
    shared_error = _shared_full_file_checks(
        raw_response,
        expected_kind="html",
        allowed_language_tags={"html"},
    )
    if shared_error is not None:
        return shared_error

    lowered = stripped_response.lower()

    if not HTML_DOCTYPE_PATTERN.match(stripped_response):
        return _format_error(
            "Model output must include a complete HTML document with <!DOCTYPE html>."
        )

    for tag_name in ("html", "head", "body"):
        if f"<{tag_name}" not in lowered or f"</{tag_name}>" not in lowered:
            return _format_error(
                f"Model output is missing the required <{tag_name}> structure."
            )

    if "<body" not in lowered or "</body>" not in lowered:
        return _format_error("Model output is missing the required <body> section.")

    stack = []
    void_elements = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    for match in HTML_TAG_PATTERN.finditer(stripped_response):
        is_closing = match.group(1) == "/"
        tag_name = match.group(2).lower()
        tag_text = match.group(0)

        if tag_name in void_elements or tag_text.endswith("/>") or tag_name == "!doctype":
            continue

        if not is_closing:
            stack.append(tag_name)
            continue

        if not stack or stack[-1] != tag_name:
            return _format_error(
                "Model output included malformed HTML structure. "
                "Expected a complete HTML file."
            )

        stack.pop()

    if stack:
        return _format_error(
            "Model output included malformed HTML structure. "
            "Expected a complete HTML file."
        )

    return _success(stripped_response)


def validate_css_full_file_submission(raw_response: str) -> ValidationResult:
    stripped_response = raw_response.strip()
    shared_error = _shared_full_file_checks(
        raw_response,
        expected_kind="css",
        allowed_language_tags=CSS_LANGUAGE_TAGS,
    )
    if shared_error is not None:
        return shared_error

    if not _has_balanced_braces(stripped_response):
        return _format_error(
            "Model output included unbalanced CSS braces. Expected a complete CSS file."
        )

    if "{" not in stripped_response or "}" not in stripped_response:
        return _format_error(
            "Model output must include selector blocks. Expected a complete CSS file."
        )

    if re.fullmatch(r"[\s\S]*:[\s\S]*;[\s\S]*", stripped_response) and not re.search(
        r"[^{]+\{[^}]*\}",
        stripped_response,
    ):
        return _format_error(
            "Model output included declarations only. Expected a complete CSS file."
        )

    if not re.search(r"[^{]+\{[^}]*\}", stripped_response):
        return _format_error(
            "Model output does not resemble a complete CSS stylesheet."
        )

    return _success(stripped_response)


def validate_javascript_full_file_submission(raw_response: str) -> ValidationResult:
    stripped_response = raw_response.strip()
    shared_error = _shared_full_file_checks(
        raw_response,
        expected_kind="javascript",
        allowed_language_tags=JAVASCRIPT_LANGUAGE_TAGS,
    )
    if shared_error is not None:
        return shared_error

    node_validation_result = _validate_javascript_syntax_with_node(stripped_response)
    if node_validation_result is not None:
        return node_validation_result

    if not _has_balanced_braces(stripped_response):
        return _format_error(
            "Model output included unbalanced JavaScript braces. "
            "Expected a complete JavaScript file."
        )

    if stripped_response.count("(") != stripped_response.count(")"):
        return _format_error(
            "Model output included malformed JavaScript syntax. "
            "Expected a complete JavaScript file."
        )

    if stripped_response.endswith(("=", "=>", "function")) or stripped_response.endswith("{"):
        return _format_error(
            "Model output appears truncated. Expected a complete JavaScript file."
        )

    return _success(stripped_response)


def validate_pug_full_file_submission(raw_response: str) -> ValidationResult:
    stripped_response = raw_response.strip()
    shared_error = _shared_full_file_checks(
        raw_response,
        expected_kind="pug",
        allowed_language_tags=PUG_LANGUAGE_TAGS,
    )
    if shared_error is not None:
        return shared_error

    if stripped_response.lower().startswith("<!doctype") or stripped_response.lstrip().startswith("<"):
        return _format_error(
            "Model output included HTML instead of the required complete Pug file."
        )

    compile_error = compile_pug_submission(stripped_response)
    if compile_error is not None:
        return _format_error(
            "Model output included invalid Pug syntax. "
            f"{compile_error}"
        )

    return _success(stripped_response)


def validate_universal_submission(problem: Problem, raw_response: str) -> ValidationResult:
    if not problem.raw_definition_json:
        return _format_error("Universal problems require a JSON definition.")

    try:
        definition = json.loads(problem.raw_definition_json)
    except (json.JSONDecodeError, TypeError):
        return _format_error("Problem definition JSON is invalid.")

    if detect_problem_schema(definition) != UNIVERSAL_SCHEMA:
        return _format_error("Problem is not a universal-schema assignment.")

    evaluator_type = definition.get("evaluatorType", "")
    language = str(definition.get("language", "")).lower()

    if evaluator_type == "browser_qunit_html" or language == "html":
        return validate_html_full_file_submission(raw_response)

    if evaluator_type == "browser_qunit_css" or language == "css":
        return validate_css_full_file_submission(raw_response)

    if evaluator_type == "browser_qunit_mocked_api" or language == "javascript":
        return validate_javascript_full_file_submission(raw_response)

    if evaluator_type == NODE_EVALUATOR_TYPE or language == "pug":
        return validate_pug_full_file_submission(raw_response)

    return _format_error("Unsupported universal problem type for validation.")
