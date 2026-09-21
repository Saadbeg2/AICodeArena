import re


FENCED_CODE_PATTERN = re.compile(
    r"```[ \t]*[A-Za-z0-9_+#.-]*[ \t]*\r?\n(.*?)```",
    re.DOTALL,
)

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


def clean_ai_code(response: str) -> str:
    """Return code without markdown fences, a language tag, or surrounding prose."""
    fenced_code = FENCED_CODE_PATTERN.search(response)

    if fenced_code is not None:
        return fenced_code.group(1).strip()

    cleaned_response = response.strip()
    lines = cleaned_response.splitlines()

    if lines and lines[0].strip().lower() in LANGUAGE_TAGS:
        lines = lines[1:]

    return "\n".join(lines).strip()


"""
Legacy helper from an earlier forgiving-cleanup design.

This module is not used in official scoring. Official evaluation now uses
submission_validator.py so model outputs with Markdown fences, language tags,
or surrounding prose can be rejected before functional tests run.
"""