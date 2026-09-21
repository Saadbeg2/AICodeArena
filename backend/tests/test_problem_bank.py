import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, get_database, get_problem_prompt, list_problems
from app.models import Problem
from app.prompt_builder import build_problem_prompt
from app.problem_loader import (
    DEFAULT_PROBLEM_BANK,
    LEGACY_SCHEMA,
    UNIVERSAL_SCHEMA,
    detect_problem_schema,
    load_problem_definition,
    load_problem_definitions,
)
from app.seed import seed_database
from tests.problem_bank_fixtures import (
    LEGACY_FIX_USER_EMAIL,
    LEGACY_MULTIPLY_NUMBERS,
    LEGACY_TIC_TAC_TOE,
    LEGACY_TWO_SUM,
    write_problem_bank,
)


class ProblemLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.starting_lineup_file = DEFAULT_PROBLEM_BANK / "starting_lineup_form.json"
        self.tic_tac_toe_file = DEFAULT_PROBLEM_BANK / "tic_tac_toe_board.json"
        self.notable_quotes_file = DEFAULT_PROBLEM_BANK / "notable_quotes.json"
        self.super_heroes_file = (
            DEFAULT_PROBLEM_BANK / "super-heroes-vs-super-villains.json"
        )
        self.todo_list_pug_file = DEFAULT_PROBLEM_BANK / "todo-list-pug.json"

    def test_detects_legacy_schema(self) -> None:
        self.assertEqual(detect_problem_schema(LEGACY_TWO_SUM), LEGACY_SCHEMA)

    def test_detects_universal_schema(self) -> None:
        definition = load_problem_definition(self.starting_lineup_file)

        self.assertEqual(detect_problem_schema(definition), UNIVERSAL_SCHEMA)

    def test_rejects_unknown_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "supported schema"):
            detect_problem_schema({"id": "broken"})

    def test_loads_valid_starting_lineup_problem(self) -> None:
        definition = load_problem_definition(self.starting_lineup_file)

        self.assertEqual(definition["id"], "starting-lineup-form")
        self.assertEqual(definition["evaluatorType"], "browser_qunit_html")

    def test_loads_valid_tic_tac_toe_problem(self) -> None:
        definition = load_problem_definition(self.tic_tac_toe_file)

        self.assertEqual(definition["id"], "tic-tac-toe-board")
        self.assertEqual(definition["evaluatorType"], "browser_qunit_css")

    def test_loads_valid_notable_quotes_problem(self) -> None:
        definition = load_problem_definition(self.notable_quotes_file)

        self.assertEqual(definition["id"], "notable-quotes")
        self.assertEqual(definition["evaluatorType"], "browser_qunit_mocked_api")

    def test_loads_valid_super_heroes_problem(self) -> None:
        definition = load_problem_definition(self.super_heroes_file)

        self.assertEqual(definition["id"], "super-heroes-vs-super-villains")
        self.assertEqual(definition["evaluatorType"], "browser_qunit_javascript")
        self.assertEqual(definition["submissionRules"]["editablePaths"], ["hero.js"])
        self.assertEqual(definition["files"][3]["path"], "styles.css")
        self.assertEqual(sum(test["points"] for test in definition["tests"]), 10)

    def test_loads_valid_todo_list_pug_problem(self) -> None:
        definition = load_problem_definition(self.todo_list_pug_file)

        self.assertEqual(definition["id"], "todo-list-pug")
        self.assertEqual(definition["evaluatorType"], "node_jest_pug_jsdom")
        self.assertEqual(definition["submissionRules"]["editablePaths"], ["views/index.pug"])
        self.assertEqual(definition["files"][2]["path"], "public/styles.css")
        self.assertEqual(sum(test["points"] for test in definition["tests"]), 10)
        self.assertEqual(definition["referenceSolution"]["files"][0]["path"], "views/index.pug")

    def test_accepts_optional_file_level_notes(self) -> None:
        definition = load_problem_definition(self.starting_lineup_file)

        self.assertIn("notes", definition["files"][1])
        self.assertIsInstance(definition["files"][1]["notes"], str)

    def test_accepts_optional_top_level_mocks(self) -> None:
        definition = load_problem_definition(self.notable_quotes_file)

        self.assertIn("mocks", definition)
        self.assertIsInstance(definition["mocks"], dict)

    def test_loads_problem_with_reference_solution(self) -> None:
        definition = load_problem_definition(self.starting_lineup_file)

        self.assertIn("referenceSolution", definition)
        self.assertEqual(definition["referenceSolution"]["source"], "zyBooks")
        self.assertEqual(
            definition["referenceSolution"]["files"][0]["path"],
            "index.html",
        )

    def test_loads_problem_without_reference_solution(self) -> None:
        definition = load_problem_definition(self.notable_quotes_file)

        self.assertIn("referenceSolution", definition)
        self.assertEqual(
            definition["referenceSolution"]["files"][0]["path"],
            "quote.js",
        )

    def test_preserves_reference_solution_content_exactly(self) -> None:
        raw_definition = json.loads(
            self.starting_lineup_file.read_text(encoding="utf-8")
        )
        loaded_definition = load_problem_definition(self.starting_lineup_file)

        self.assertEqual(
            loaded_definition["referenceSolution"]["files"][0]["content"],
            raw_definition["referenceSolution"]["files"][0]["content"],
        )

    def test_rejects_missing_universal_required_field(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            broken_definition = load_problem_definition(self.starting_lineup_file)
            del broken_definition["runtime"]
            write_problem_bank(problem_bank, [broken_definition])

            with self.assertRaisesRegex(ValueError, "missing required field: runtime"):
                load_problem_definition(problem_bank / "starting-lineup-form.json")

    def test_rejects_unsafe_file_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            broken_definition = load_problem_definition(self.starting_lineup_file)
            broken_definition["files"][0]["path"] = "../index.html"
            write_problem_bank(problem_bank, [broken_definition])

            with self.assertRaisesRegex(ValueError, "unsafe file path"):
                load_problem_definition(problem_bank / "starting-lineup-form.json")

    def test_rejects_editable_paths_that_do_not_match_editable_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            broken_definition = load_problem_definition(self.tic_tac_toe_file)
            broken_definition["submissionRules"]["editablePaths"] = ["index.html"]
            write_problem_bank(problem_bank, [broken_definition])

            with self.assertRaisesRegex(ValueError, "editablePaths must match editable files"):
                load_problem_definition(problem_bank / "tic-tac-toe-board.json")

    def test_rejects_duplicate_test_ids(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            broken_definition = load_problem_definition(self.notable_quotes_file)
            broken_definition["tests"][1]["id"] = broken_definition["tests"][0]["id"]
            write_problem_bank(problem_bank, [broken_definition])

            with self.assertRaisesRegex(ValueError, "duplicate test ids"):
                load_problem_definition(problem_bank / "notable-quotes.json")

    def test_rejects_empty_test_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            broken_definition = load_problem_definition(self.notable_quotes_file)
            broken_definition["tests"][0]["source"] = "   "
            write_problem_bank(problem_bank, [broken_definition])

            with self.assertRaisesRegex(ValueError, "test source must be non-empty"):
                load_problem_definition(problem_bank / "notable-quotes.json")

    def test_rejects_malformed_reference_solution(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            broken_definition = load_problem_definition(self.starting_lineup_file)
            broken_definition["referenceSolution"] = {"source": "zyBooks", "files": "bad"}
            write_problem_bank(problem_bank, [broken_definition])

            with self.assertRaisesRegex(
                ValueError,
                "referenceSolution.files must be a non-empty list",
            ):
                load_problem_definition(problem_bank / "starting-lineup-form.json")

    def test_rejects_duplicate_reference_solution_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            broken_definition = load_problem_definition(self.starting_lineup_file)
            broken_definition["referenceSolution"]["files"].append(
                copy.deepcopy(broken_definition["referenceSolution"]["files"][0])
            )
            write_problem_bank(problem_bank, [broken_definition])

            with self.assertRaisesRegex(
                ValueError,
                "referenceSolution contains duplicate file paths",
            ):
                load_problem_definition(problem_bank / "starting-lineup-form.json")

    def test_rejects_reference_solution_path_that_is_not_editable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            broken_definition = load_problem_definition(self.starting_lineup_file)
            broken_definition["referenceSolution"]["files"][0]["path"] = "styles.css"
            write_problem_bank(problem_bank, [broken_definition])

            with self.assertRaisesRegex(
                ValueError,
                "referenceSolution path must match an editable file",
            ):
                load_problem_definition(problem_bank / "starting-lineup-form.json")

    def test_rejects_incorrect_maximum_points(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            broken_definition = load_problem_definition(self.starting_lineup_file)
            broken_definition["scoring"]["maximumPoints"] = 999
            write_problem_bank(problem_bank, [broken_definition])

            with self.assertRaisesRegex(ValueError, "maximumPoints must equal the sum of test points"):
                load_problem_definition(problem_bank / "starting-lineup-form.json")

    def test_legacy_problem_loading_still_works(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            write_problem_bank(
                problem_bank,
                [LEGACY_TWO_SUM, LEGACY_FIX_USER_EMAIL, LEGACY_MULTIPLY_NUMBERS],
            )

            definitions = load_problem_definitions(problem_bank)

        self.assertEqual(len(definitions), 3)
        self.assertEqual(definitions[0]["id"], "fix_user_email")
        self.assertEqual(definitions[1]["id"], "multiply_numbers")
        self.assertEqual(definitions[2]["id"], "two_sum")


class ProblemSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(bind=self.engine)
        seed_database(self.engine, self.session_factory)
        self.database = self.session_factory()

        def override_database():
            try:
                yield self.database
            finally:
                pass

        app.dependency_overrides[get_database] = override_database
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        self.database.close()
        self.engine.dispose()

    def test_seed_maps_universal_problem_into_sqlite(self) -> None:
        problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "starting-lineup-form")
        )
        raw_definition = json.loads(problem.raw_definition_json)

        self.assertEqual(problem.problem_type, "browser_qunit_html")
        self.assertEqual(problem.category, "html-form")
        self.assertEqual(problem.language, "html")
        self.assertEqual(problem.required_file, "index.html")
        self.assertEqual(problem.required_function, "")
        self.assertEqual(problem.starter_code, raw_definition["files"][0]["content"])

    def test_hidden_tests_are_not_copied_into_public_index_fields(self) -> None:
        problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "notable-quotes")
        )

        self.assertNotIn("QUnit.test", problem.starter_code)
        self.assertNotIn("points", problem.description.lower())
        self.assertEqual(problem.required_file, "quote.js")
        self.assertEqual(problem.required_function, "")

    def test_problems_endpoint_lists_universal_problem_rows(self) -> None:
        problems = list_problems(self.database)

        self.assertEqual(len(problems), 5)
        self.assertEqual(problems[0].problem_key, "notable-quotes")
        self.assertEqual(problems[1].problem_key, "starting-lineup-form")
        self.assertEqual(problems[2].problem_key, "super-heroes-vs-super-villains")
        self.assertEqual(problems[3].problem_key, "tic-tac-toe-board")
        self.assertEqual(problems[4].problem_key, "todo-list-pug")

    def test_problem_prompt_for_universal_problem_hides_tests(self) -> None:
        problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "starting-lineup-form")
        )

        response = get_problem_prompt(problem.id, self.database)

        self.assertIn("Editable files: index.html", response.prompt)
        self.assertNotIn("QUnit.test", response.prompt)
        self.assertNotIn("points", response.prompt.lower())

    def test_universal_prompt_includes_student_prompt_and_strict_rules(self) -> None:
        problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "starting-lineup-form")
        )

        response = get_problem_prompt(problem.id, self.database)

        self.assertIn("Add a form to index.html", response.prompt)
        self.assertIn("Required submission file: index.html", response.prompt)
        self.assertIn("Submission mode: full_editable_file", response.prompt)
        self.assertIn("Return the complete contents of the editable file.", response.prompt)
        self.assertIn("Do not include a filename heading.", response.prompt)

    def test_universal_prompt_shows_read_only_file_when_allowed(self) -> None:
        problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "notable-quotes")
        )

        response = get_problem_prompt(problem.id, self.database)

        self.assertIn("- index.html [read-only]", response.prompt)
        self.assertIn("- quote.js [editable]", response.prompt)

    def test_universal_prompt_omits_read_only_files_when_disallowed(self) -> None:
        problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "starting-lineup-form")
        )

        response = get_problem_prompt(problem.id, self.database)

        self.assertNotIn("- styles.css [read-only]", response.prompt)

    def test_universal_prompt_hides_evaluator_mocks_and_known_issues(self) -> None:
        problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "notable-quotes")
        )

        response = get_problem_prompt(problem.id, self.database)

        self.assertNotIn("browser_qunit_mocked_api", response.prompt)
        self.assertNotIn("replaceableGlobals", response.prompt)
        self.assertNotIn("knownIssues", response.prompt)

    def test_universal_prompt_excludes_reference_solution(self) -> None:
        problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "starting-lineup-form")
        )

        response = get_problem_prompt(problem.id, self.database)
        reference_content = json.loads(problem.raw_definition_json)[
            "referenceSolution"
        ]["files"][0]["content"]

        self.assertNotIn("referenceSolution", response.prompt)
        self.assertNotIn(reference_content, response.prompt)

    def test_student_facing_problem_endpoints_do_not_leak_reference_solution(self) -> None:
        problem = self.database.scalar(
            select(Problem).where(Problem.problem_key == "starting-lineup-form")
        )
        problems_response = self.client.get("/problems")
        problem_response = self.client.get(f"/problems/{problem.id}")

        self.assertEqual(problems_response.status_code, 200)
        self.assertEqual(problem_response.status_code, 200)
        self.assertNotIn("referenceSolution", problems_response.text)
        self.assertNotIn("referenceSolution", problem_response.text)

    def test_legacy_prompt_behavior_remains_unchanged(self) -> None:
        problem = Problem(
            title="Two Sum",
            category="Arrays",
            difficulty="Easy",
            language="Python",
            description="Return the indices of two numbers that add up to the target.",
            starter_code="def two_sum(numbers, target):\n    pass\n",
            required_file="solution.py",
            required_function="two_sum",
        )

        prompt = build_problem_prompt(problem)

        self.assertIn("Write the complete solution in a file named solution.py.", prompt)
        self.assertIn("Define the required function: two_sum.", prompt)
        self.assertIn("Do not include explanations before or after the code.", prompt)

    def test_seed_still_supports_legacy_bank_mappings(self) -> None:
        with TemporaryDirectory() as temp_dir:
            problem_bank = Path(temp_dir)
            write_problem_bank(
                problem_bank,
                [
                    copy.deepcopy(LEGACY_TWO_SUM),
                    copy.deepcopy(LEGACY_FIX_USER_EMAIL),
                    copy.deepcopy(LEGACY_MULTIPLY_NUMBERS),
                    copy.deepcopy(LEGACY_TIC_TAC_TOE),
                ],
            )
            engine = create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            session_factory = sessionmaker(bind=engine)

            try:
                seed_database(engine, session_factory, problem_bank)
                database = session_factory()
                try:
                    two_sum = database.scalar(
                        select(Problem).where(Problem.problem_key == "two_sum")
                    )
                    css_problem = database.scalar(
                        select(Problem).where(
                            Problem.problem_key == "tic_tac_toe_board"
                        )
                    )
                finally:
                    database.close()
            finally:
                engine.dispose()

        self.assertEqual(two_sum.problem_type, "function")
        self.assertEqual(two_sum.required_function, "two_sum")
        self.assertEqual(css_problem.problem_type, "css_static_region")
        self.assertEqual(css_problem.required_file, "styles.css")


if __name__ == "__main__":
    unittest.main()
