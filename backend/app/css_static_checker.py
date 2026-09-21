import json
import re

from app.models import Problem


TODO_MARKER_FALLBACK = "/* TODO: Add your solution here */"
SLOW_SENTINEL = "/* AICODEARENA_SLOW */"


def _normalize_css_value(value: str) -> str:
    lowered = value.strip().lower()
    return re.sub(r"\s+", " ", lowered)


def _parse_css_declarations(block: str) -> dict[str, str]:
    declarations = {}

    for declaration in block.split(";"):
        stripped = declaration.strip()
        if not stripped or stripped.startswith("/*"):
            continue
        if ":" not in stripped:
            continue
        property_name, property_value = stripped.split(":", 1)
        declarations[property_name.strip().lower()] = _normalize_css_value(
            property_value
        )

    return declarations


def assemble_css_region_submission(problem: Problem, submission: str) -> str:
    if not problem.raw_definition_json:
        raise ValueError("CSS static region problems require a JSON definition")

    definition = json.loads(problem.raw_definition_json)
    editable_region = definition.get("editable_region", {})
    marker = editable_region.get("marker", TODO_MARKER_FALLBACK)
    editable_file = next(
        file_definition
        for file_definition in definition["files"]
        if file_definition["editable"]
    )
    starter_css = editable_file["starter_content"]

    if marker not in starter_css:
        raise ValueError("Could not find the editable CSS TODO region")

    inserted_block = "\n".join(
        f"    {line.rstrip()}"
        for line in submission.strip().splitlines()
    )
    return starter_css.replace(marker, inserted_block)


def evaluate_css_static_region(problem: Problem, submission: str) -> dict:
    if SLOW_SENTINEL in submission:
        return {
            "status": "Time Limit Exceeded",
            "stdout": None,
            "stderr": "CSS evaluation timed out in mock mode.",
            "compile_output": None,
            "time": "5.000",
            "memory": None,
        }

    if not problem.raw_definition_json:
        raise ValueError("CSS static region problems require a JSON definition")

    definition = json.loads(problem.raw_definition_json)
    completed_css = assemble_css_region_submission(problem, submission)
    selector = definition["checks"]["required_selector"]
    pattern = re.compile(re.escape(selector) + r"\s*\{(.*?)\}", re.DOTALL)
    match = pattern.search(completed_css)

    if match is None:
        return {
            "status": "Wrong Answer",
            "stdout": "Score: 0/100",
            "stderr": f"Could not find the {selector} rule in styles.css.",
            "compile_output": completed_css,
            "time": None,
            "memory": None,
        }

    declarations = _parse_css_declarations(match.group(1))
    individual_results = []
    score = 0

    for check in definition["checks"]["required_declarations"]:
        property_name = check["property"].lower()
        accepted_values = {
            _normalize_css_value(value)
            for value in check["accepted_values"]
        }
        candidate_properties = [property_name] + [
            alternative.lower()
            for alternative in check.get("alternate_properties", [])
        ]
        matched_property = next(
            (
                candidate
                for candidate in candidate_properties
                if candidate in declarations
            ),
            None,
        )

        if matched_property is None:
            individual_results.append(
                f"Missing required declaration: {property_name}."
            )
            continue

        actual_value = declarations[matched_property]
        if actual_value not in accepted_values:
            individual_results.append(
                f"{matched_property} has value {actual_value!r}, expected one of "
                f"{sorted(accepted_values)!r}."
            )
            continue

        score += 20
        individual_results.append(f"{matched_property} passed.")

    passed = score == 100
    return {
        "status": "Accepted" if passed else "Wrong Answer",
        "stdout": "PASS" if passed else f"Score: {score}/100",
        "stderr": None if passed else "\n".join(individual_results),
        "compile_output": completed_css,
        "time": None,
        "memory": None,
        "score": score,
        "total": 100,
        "passed": passed,
        "checks": individual_results,
    }
