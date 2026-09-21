import unittest

from app.code_cleaner import clean_ai_code


class CodeCleanerTests(unittest.TestCase):
    """Legacy cleaner behavior kept for optional/manual debugging only."""

    def test_removes_fences_language_tag_and_surrounding_text(self) -> None:
        response = """Here is the solution:

```python
def add(a, b):
    return a + b
```

This solution returns the sum.
"""

        expected = """def add(a, b):
    return a + b"""

        self.assertEqual(clean_ai_code(response), expected)

    def test_removes_plain_language_tag(self) -> None:
        response = """python
def greet():
    return "Hello"
"""

        expected = 'def greet():\n    return "Hello"'

        self.assertEqual(clean_ai_code(response), expected)

    def test_keeps_plain_code_and_trims_whitespace(self) -> None:
        response = "\n\ndef answer():\n    return 42\n\n"

        self.assertEqual(clean_ai_code(response), "def answer():\n    return 42")


if __name__ == "__main__":
    unittest.main()
