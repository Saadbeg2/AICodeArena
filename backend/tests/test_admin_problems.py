import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import (
    get_admin_problem_definition,
    import_admin_problem,
    list_problems,
)


class AdminProblemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.problem_bank = Path(self.temporary_directory.name)
        self.bank_patch = patch(
            "app.main.PROBLEM_BANK_PATH",
            self.problem_bank,
        )
        self.bank_patch.start()

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        TestSession = sessionmaker(bind=self.engine)
        self.database = TestSession()

        self.definition = {
            "id": "reverse_text",
            "title": "Reverse Text",
            "type": "function",
            "language": "python",
            "description": "Return the supplied text in reverse order.",
            "function_signature": "def reverse_text(text):",
            "files": [
                {
                    "filename": "solution.py",
                    "editable": True,
                    "starter_content": "def reverse_text(text):\n    pass\n",
                }
            ],
            "tests": {
                "visible": [
                    {"input": {"text": "abc"}, "expected": "cba"}
                ],
                "hidden": [],
            },
            "metadata": {
                "difficulty": "easy",
                "source": "custom",
                "tags": ["strings"],
            },
        }

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()
        self.bank_patch.stop()
        self.temporary_directory.cleanup()

    def test_import_saves_valid_problem_json(self) -> None:
        response = import_admin_problem(
            self.definition,
            False,
            self.database,
        )

        self.assertEqual(response["problem_key"], "reverse_text")
        self.assertEqual(response["file_count"], 1)
        saved_definition = json.loads(
            (self.problem_bank / "reverse_text.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved_definition, self.definition)

    def test_imported_problem_appears_in_problems_endpoint(self) -> None:
        import_admin_problem(self.definition, False, self.database)

        problems = list_problems(self.database)

        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].title, "Reverse Text")

    def test_duplicate_without_overwrite_is_rejected(self) -> None:
        import_admin_problem(self.definition, False, self.database)

        with self.assertRaises(HTTPException) as raised:
            import_admin_problem(self.definition, False, self.database)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("overwrite=true", raised.exception.detail)

    def test_duplicate_with_overwrite_updates_problem(self) -> None:
        import_admin_problem(self.definition, False, self.database)
        updated_definition = {**self.definition, "title": "Reverse a String"}

        response = import_admin_problem(
            updated_definition,
            True,
            self.database,
        )
        problems = list_problems(self.database)

        self.assertEqual(response["title"], "Reverse a String")
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].title, "Reverse a String")

    def test_path_traversal_id_is_rejected(self) -> None:
        invalid_definition = {**self.definition, "id": "../outside"}

        with self.assertRaises(HTTPException) as raised:
            import_admin_problem(invalid_definition, False, self.database)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse((self.problem_bank.parent / "outside.json").exists())

    def test_missing_required_field_is_rejected(self) -> None:
        invalid_definition = dict(self.definition)
        del invalid_definition["description"]

        with self.assertRaises(HTTPException) as raised:
            import_admin_problem(invalid_definition, False, self.database)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("description", raised.exception.detail)

    def test_definition_endpoint_returns_saved_json(self) -> None:
        import_admin_problem(self.definition, False, self.database)

        response = get_admin_problem_definition("reverse_text")

        self.assertEqual(response, self.definition)


if __name__ == "__main__":
    unittest.main()
