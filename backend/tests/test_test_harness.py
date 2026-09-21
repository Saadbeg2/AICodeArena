import io
import unittest
from contextlib import redirect_stdout

from app.test_harness import build_python_test_harness


CORRECT_SOLUTION = """def two_sum(numbers, target):
    seen = {}

    for index, number in enumerate(numbers):
        if target - number in seen:
            return [seen[target - number], index]

        seen[number] = index

    return []"""

INCORRECT_SOLUTION = """def two_sum(numbers, target):
    return [0, 0]"""


class TestHarnessTests(unittest.TestCase):
    def test_correct_solution_passes(self) -> None:
        harness = build_python_test_harness(CORRECT_SOLUTION)
        output = io.StringIO()

        with redirect_stdout(output):
            exec(harness, {})

        self.assertEqual(output.getvalue().strip(), "PASS")

    def test_incorrect_solution_fails(self) -> None:
        harness = build_python_test_harness(INCORRECT_SOLUTION)

        with self.assertRaisesRegex(AssertionError, "invalid indices"):
            exec(harness, {})

    def test_harness_contains_submitted_solution(self) -> None:
        harness = build_python_test_harness(CORRECT_SOLUTION)

        self.assertIn(CORRECT_SOLUTION, harness)


if __name__ == "__main__":
    unittest.main()
