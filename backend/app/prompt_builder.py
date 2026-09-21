import json
from textwrap import indent

from app.models import Problem
from app.problem_loader import UNIVERSAL_SCHEMA, detect_problem_schema


# Prompt builder and submission_validator.py work together:
#
# 1. This file tells the model the output contract:
#    - return only raw executable code
#    - do not include Markdown fences
#    - do not include a language label
#    - do not include explanations before or after the code
#
# 2. submission_validator.py enforces that contract before the test harness runs.
#
# This keeps AICodeArena strict and fair. The system does not clean or repair
# model output during official scoring. If a model ignores the prompt format,
# the run fails as a formatting error before functional tests are executed.

def _build_json_problem_prompt(problem: Problem, definition: dict) -> str:
    if detect_problem_schema(definition) == UNIVERSAL_SCHEMA:
        prompt_policy = definition.get("promptPolicy", {})
        submission_rules = definition.get("submissionRules", {})
        editable_paths = submission_rules.get("editablePaths", [])
        editable_files = []
        file_sections = []

        for file_definition in definition["files"]:
            role = file_definition["role"]
            include_in_prompt = file_definition.get("includeInPrompt", False)

            if role == "editable":
                editable_files.append(file_definition["path"])

            if role != "editable" and (
                not include_in_prompt or not prompt_policy.get("showReadOnlyFiles", False)
            ):
                continue

            if role == "editable" and not include_in_prompt:
                continue

            content = (file_definition.get("content") or "").rstrip() or "[no content provided]"
            role_label = "editable" if role == "editable" else "read-only"
            file_sections.append(
                f"- {file_definition['path']} [{role_label}]\n"
                f"  File content:\n"
                f"{indent(content, '    ')}"
            )

        editable_files_text = ", ".join(editable_files) or "None"
        required_submission_file = (
            editable_paths[0] if editable_paths else editable_files[0]
        )
        file_section_text = "\n".join(file_sections) or "- No prompt-visible files."

        return f"""Solve the following coding problem.

Title: {definition['title']}
Difficulty: {problem.difficulty}
Language: {definition['language']}

Problem description:
{definition['description']}

Instructions:
{definition['instructions']['studentPrompt']}

Submission mode: {submission_rules.get('mode', 'Not specified')}
Required submission file: {required_submission_file}
Editable files: {editable_files_text}

Files included in this prompt:
{file_section_text}

Requirements:
- Return the complete contents of the editable file.
- Return only the required submission file: {required_submission_file}.
- Do not include Markdown code fences.
- Do not include explanations.
- Do not include a filename heading.
- Do not include any other files.
- Do not modify read-only files.
"""

    if definition["type"] == "css_static_region":
        editable_region = definition.get("editable_region", {})
        editable_file = next(
            file_definition
            for file_definition in definition["files"]
            if file_definition["editable"]
        )
        locked_files = [
            file_definition["filename"]
            for file_definition in definition["files"]
            if not file_definition["editable"]
        ]
        locked_file_text = ", ".join(locked_files) or "None"
        return f"""Solve the following coding problem.

Title: {definition['title']}
Type: {definition['type']}
Difficulty: {problem.difficulty}
Language: {definition['language']}

Problem description:
{definition['description']}

Locked files: {locked_file_text}
Editable file: {editable_file['filename']}
Editable region: inside the {editable_region.get('selector', '#board')} rule where the TODO comment appears

Files:
- {definition['files'][0]['filename']} (editable: no) [locked]
  File content:
{indent(definition['files'][0]['starter_content'].rstrip(), '  ')}
- {editable_file['filename']} (editable: yes) [editable]
  Starter content:
{indent(editable_file['starter_content'].rstrip(), '  ')}

Requirements:
- {definition['files'][0]['filename']} is read-only and must remain unchanged.
- Only complete the TODO region inside the {editable_region.get('selector', '#board')} rule.
- Return only CSS declarations for the {editable_region.get('selector', '#board')} rule.
- Do not include {editable_region.get('selector', '#board')} {{ }}.
- Do not include the full {editable_file['filename']} file.
- Do not include Markdown code fences.
- Do not include explanations before or after the CSS.
- Do not include a language label.
- Any extra formatting will be treated as a formatting failure.
"""

    file_sections = []
    editable_files = []
    locked_files = []

    for file_definition in definition["files"]:
        editable = "yes" if file_definition["editable"] else "no"
        status = "editable" if file_definition["editable"] else "locked"
        content_label = (
            "Starter content" if file_definition["editable"] else "File content"
        )
        file_content = indent(file_definition["starter_content"].rstrip(), "  ")
        file_sections.append(
            f"- {file_definition['filename']} (editable: {editable}) [{status}]\n"
            f"  {content_label}:\n{file_content}"
        )

        if file_definition["editable"]:
            editable_files.append(file_definition["filename"])
        else:
            locked_files.append(file_definition["filename"])

    files_text = "\n".join(file_sections)
    function_signature = definition.get("function_signature", "Not specified")
    editable_files_text = ", ".join(editable_files) or "None"
    locked_files_text = ", ".join(locked_files) or "None"

    return f"""Solve the following coding problem.

Title: {definition['title']}
Type: {definition['type']}
Difficulty: {problem.difficulty}
Language: {definition['language']}

Problem description:
{definition['description']}

Required function signature:
{function_signature}

Files:
{files_text}

Editable files: {editable_files_text}
Locked files: {locked_files_text}

Requirements:
- Only modify files marked as editable.
- Locked files are read-only and must remain unchanged.
- Preserve the required function signature.
- Return only the contents of the editable file.
- Return only raw executable code.
- Do not include Markdown code fences.
- Do not include a language label.
- Do not include explanations before or after the code.
- Any formatting outside raw code will be treated as a formatting failure.
"""
# These formatting rules are intentionally strict. They match the checks in
# submission_validator.py, so the prompt tells the model the same rules that
# official scoring later enforces.


def build_problem_prompt(problem: Problem) -> str:
    """Build a standard prompt from JSON data or legacy database fields."""
    if problem.raw_definition_json:
        try:
            definition = json.loads(problem.raw_definition_json)
            return _build_json_problem_prompt(problem, definition)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    return f"""Solve the following coding problem.

Title: {problem.title}
Category: {problem.category}
Difficulty: {problem.difficulty}
Language: {problem.language}

Problem description:
{problem.description}

Starter code:
{problem.starter_code}
Requirements:
- Write the complete solution in a file named {problem.required_file}.
- Define the required function: {problem.required_function}.
- Use {problem.language}.
- Return only the contents of {problem.required_file}.
- Return only raw executable code.
- Do not include Markdown code fences.
- Do not include a language label.
- Do not include explanations before or after the code.
- Any formatting outside raw code will be treated as a formatting failure.
"""
