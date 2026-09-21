import json

from app.models import Problem


SAMPLE_TWO_SUM_SOLUTION = """def two_sum(numbers: list[int], target: int) -> list[int]:
    seen = {}

    for index, number in enumerate(numbers):
        needed = target - number

        if needed in seen:
            return [seen[needed], index]

        seen[number] = index

    return []"""


TWO_SUM_TEST_SUITE = '''

def _run_tests() -> None:
    test_cases = [
        ([2, 7, 11, 15], 9),
        ([3, 2, 4], 6),
        ([3, 3], 6),
        ([-1, -2, -3, -4, -5], -8),
    ]

    for numbers, target in test_cases:
        result = two_sum(numbers.copy(), target)

        if not isinstance(result, list) or len(result) != 2:
            raise AssertionError(
                f"two_sum({numbers}, {target}) returned {result!r}; "
                "expected a list containing two indices"
            )

        first_index, second_index = result
        valid_indices = all(
            isinstance(index, int) and 0 <= index < len(numbers)
            for index in result
        )

        if not valid_indices or first_index == second_index:
            raise AssertionError(
                f"two_sum({numbers}, {target}) returned invalid indices {result!r}"
            )

        if numbers[first_index] + numbers[second_index] != target:
            raise AssertionError(
                f"two_sum({numbers}, {target}) returned {result!r}, but the "
                "values at those indices do not add up to the target"
            )

    print("PASS")


_run_tests()
'''


FIX_USER_EMAIL_TEST_SUITE = '''

def _run_tests() -> None:
    test_cases = [
        (User("Alice", "ALICE@EXAMPLE.COM"), "alice@example.com"),
        (User("Bob"), None),
    ]

    for user, expected in test_cases:
        result = get_user_email(user)

        if result != expected:
            raise AssertionError(
                f"get_user_email({user.name!r}) returned {result!r}; "
                f"expected {expected!r}"
            )

    print("PASS")


_run_tests()
'''


def build_two_sum_test_harness(solution_code: str) -> str:
    """Combine a Two Sum solution and its current single-file tests."""
    return f"{solution_code.strip()}\n{TWO_SUM_TEST_SUITE.lstrip()}"


def build_fix_user_email_test_harness(
    solution_code: str,
    locked_user_code: str,
) -> str:
    """Combine locked user.py, submitted service.py, and focused tests."""
    return (
        f"{locked_user_code.strip()}\n\n"
        f"{solution_code.strip()}\n\n"
        f"{FIX_USER_EMAIL_TEST_SUITE.lstrip()}"
    )


def build_generic_function_test_harness(
    problem: Problem,
    solution_code: str,
) -> str:
    """Build a harness for one-file Python functions with JSON test cases."""
    if not problem.raw_definition_json:
        raise ValueError("Generic function problems require a JSON definition")

    definition = json.loads(problem.raw_definition_json)
    editable_files = [
        file_definition
        for file_definition in definition["files"]
        if file_definition["editable"]
    ]

    if (
        definition["language"].lower() != "python"
        or definition["type"] != "function"
        or len(definition["files"]) != 1
        or len(editable_files) != 1
    ):
        raise ValueError(
            "Generic execution supports one-file Python function problems"
        )

    function_name = problem.required_function
    test_cases = definition["tests"]["visible"] + definition["tests"]["hidden"]

    if not function_name:
        raise ValueError("Generic function problem is missing a required function")

    if not test_cases:
        raise ValueError("Generic function problem must define at least one test")

    for test_case in test_cases:
        if (
            not isinstance(test_case, dict)
            or not isinstance(test_case.get("input"), dict)
            or "expected" not in test_case
        ):
            raise ValueError(
                "Generic function tests require input and expected fields"
            )

    test_cases_source = repr(test_cases)
    test_suite = f'''

def _run_tests() -> None:
    test_cases = {test_cases_source}

    for case in test_cases:
        arguments = case["input"]
        expected = case["expected"]
        result = {function_name}(**arguments)

        if result != expected:
            raise AssertionError(
                f"{function_name}(**{{arguments!r}}) returned {{result!r}}; "
                f"expected {{expected!r}}"
            )

    print("PASS")


_run_tests()
'''
    return f"{solution_code.strip()}\n{test_suite.lstrip()}"


def build_problem_test_harness(problem: Problem, solution_code: str) -> str:
    """Dispatch to one of the small problem-specific Python harnesses."""
    if problem.problem_key == "fix_user_email" and problem.raw_definition_json:
        definition = json.loads(problem.raw_definition_json)
        locked_user_file = next(
            file_definition
            for file_definition in definition["files"]
            if file_definition["filename"] == "user.py"
            and not file_definition["editable"]
        )
        return build_fix_user_email_test_harness(
            solution_code,
            locked_user_file["starter_content"],
        )

    if problem.problem_key == "two_sum":
        return build_two_sum_test_harness(solution_code)

    if problem.raw_definition_json:
        definition = json.loads(problem.raw_definition_json)

        if (
            definition.get("language", "").lower() == "python"
            and definition.get("type") == "function"
        ):
            return build_generic_function_test_harness(problem, solution_code)

    return build_two_sum_test_harness(solution_code)


def build_python_test_harness(solution_code: str) -> str:
    """Build the current Python harness; problem dispatch can be added later."""
    return build_two_sum_test_harness(solution_code)
