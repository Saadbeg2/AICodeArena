import unittest

from app.submission_validator import (
    validate_css_full_file_submission,
    validate_html_full_file_submission,
    validate_javascript_full_file_submission,
    validate_raw_code_submission,
)


class SubmissionValidatorTests(unittest.TestCase):
    def test_accepts_raw_python_code(self) -> None:
        response = """def answer():
    return 42
"""

        result = validate_raw_code_submission(response)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.code, "def answer():\n    return 42")
        self.assertIsNone(result.error_message)

    def test_rejects_markdown_fences(self) -> None:
        response = """```python
def answer():
    return 42
```"""

        result = validate_raw_code_submission(response)

        self.assertFalse(result.is_valid)
        self.assertIsNone(result.code)
        self.assertIn("Markdown fences", result.error_message)

    def test_rejects_language_label(self) -> None:
        response = """python
def answer():
    return 42
"""

        result = validate_raw_code_submission(response)

        self.assertFalse(result.is_valid)
        self.assertIn("language label", result.error_message)

    def test_rejects_explanatory_text(self) -> None:
        response = """Here is the solution:
def answer():
    return 42
"""

        result = validate_raw_code_submission(response)

        self.assertFalse(result.is_valid)
        self.assertIn("non-code text", result.error_message)

    def test_accepts_valid_full_html(self) -> None:
        response = """<!DOCTYPE html>
<html lang="en">
<head>
  <title>Demo</title>
</head>
<body>
  <p>Hello</p>
</body>
</html>"""

        result = validate_html_full_file_submission(response)

        self.assertTrue(result.is_valid)
        self.assertIn("<body>", result.code)

    def test_rejects_html_fragment(self) -> None:
        result = validate_html_full_file_submission("<p>Hello</p>")

        self.assertFalse(result.is_valid)
        self.assertIn("complete HTML", result.error_message)

    def test_rejects_fenced_html(self) -> None:
        result = validate_html_full_file_submission(
            """```html
<!DOCTYPE html>
<html><head></head><body></body></html>
```"""
        )

        self.assertFalse(result.is_valid)
        self.assertIn("Markdown fences", result.error_message)

    def test_rejects_prose_wrapped_html(self) -> None:
        result = validate_html_full_file_submission(
            """Here is index.html:
<!DOCTYPE html>
<html><head></head><body></body></html>"""
        )

        self.assertFalse(result.is_valid)
        self.assertIn("explanatory prose", result.error_message)

    def test_rejects_html_missing_body(self) -> None:
        result = validate_html_full_file_submission(
            """<!DOCTYPE html>
<html>
<head><title>Demo</title></head>
</html>"""
        )

        self.assertFalse(result.is_valid)
        self.assertIn("<body>", result.error_message)

    def test_accepts_valid_full_stylesheet(self) -> None:
        result = validate_css_full_file_submission(
            """#board {
  display: grid;
}"""
        )

        self.assertTrue(result.is_valid)
        self.assertIn("#board", result.code)

    def test_rejects_declaration_only_css(self) -> None:
        result = validate_css_full_file_submission(
            """display: grid;
grid-template-columns: 100px 100px 100px;"""
        )

        self.assertFalse(result.is_valid)
        self.assertIn("complete CSS file", result.error_message)

    def test_rejects_fenced_css(self) -> None:
        result = validate_css_full_file_submission(
            """```css
#board {
  display: grid;
}
```"""
        )

        self.assertFalse(result.is_valid)
        self.assertIn("Markdown fences", result.error_message)

    def test_rejects_unbalanced_css_braces(self) -> None:
        result = validate_css_full_file_submission(
            """#board {
  display: grid;
"""
        )

        self.assertFalse(result.is_valid)
        self.assertIn("unbalanced CSS braces", result.error_message)

    def test_rejects_prose_wrapped_css(self) -> None:
        result = validate_css_full_file_submission(
            """Here is styles.css:
#board {
  display: grid;
}"""
        )

        self.assertFalse(result.is_valid)
        self.assertIn("explanatory prose", result.error_message)

    def test_accepts_valid_full_javascript_file(self) -> None:
        result = validate_javascript_full_file_submission(
            """window.addEventListener("load", function () {
  console.log("ready");
});
"""
        )

        self.assertTrue(result.is_valid)
        self.assertIn("console.log", result.code)

    def test_rejects_fenced_javascript(self) -> None:
        result = validate_javascript_full_file_submission(
            """```javascript
function demo() {}
```"""
        )

        self.assertFalse(result.is_valid)
        self.assertIn("Markdown fences", result.error_message)

    def test_rejects_prose_wrapped_javascript(self) -> None:
        result = validate_javascript_full_file_submission(
            """Here is quote.js:
function demo() {}
"""
        )

        self.assertFalse(result.is_valid)
        self.assertIn("explanatory prose", result.error_message)

    def test_rejects_empty_javascript(self) -> None:
        result = validate_javascript_full_file_submission("   ")

        self.assertFalse(result.is_valid)
        self.assertIn("empty", result.error_message)

    def test_rejects_obvious_javascript_syntax_error(self) -> None:
        result = validate_javascript_full_file_submission(
            """function demo( {
  console.log("broken");
}
"""
        )

        self.assertFalse(result.is_valid)
        self.assertTrue(
            "invalid JavaScript syntax" in result.error_message
            or "malformed JavaScript syntax" in result.error_message
        )


if __name__ == "__main__":
    unittest.main()
