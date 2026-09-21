import json
import unittest
from unittest.mock import patch

from app.main import evaluate_universal_problem
from app.models import Problem
from app.node_jest_pug_evaluator import (
    NODE_EVALUATOR_TYPE,
    create_node_workspace,
    ensure_node_evaluator_dependencies,
    evaluate_node_jest_pug_problem,
    node_runtime_available,
)
from app.submission_validator import validate_universal_submission


PASSING_PUG_SOURCE = """ul
  each item in todoList
    li= item
"""

FAILING_PUG_SOURCE = """ul
  li Nope
"""

BROKEN_PUG_SOURCE = """ul
  each item in todoList
    li= item(
"""


def build_node_problem_definition(test_source: str, timeout_ms: int = 3000) -> dict:
    return {
        "schemaVersion": "1.0",
        "id": "pug-demo",
        "title": "Pug Demo",
        "description": "Render a todo list.",
        "course": "COSC 4398",
        "sourcePlatform": "custom",
        "assignmentType": "node-template",
        "evaluatorType": NODE_EVALUATOR_TYPE,
        "language": "pug",
        "technologies": ["Node.js", "Pug", "Jest", "jsdom"],
        "instructions": {
            "studentPrompt": "Return only the complete contents of views/index.pug."
        },
        "files": [
            {
                "path": "views/index.pug",
                "role": "editable",
                "language": "pug",
                "content": "p Placeholder",
                "includeInPrompt": True,
                "requiredInSubmission": True,
                "preserve": False,
            },
            {
                "path": "server.js",
                "role": "read_only",
                "language": "javascript",
                "content": "module.exports = {};",
                "includeInPrompt": True,
                "requiredInSubmission": False,
                "preserve": True,
            },
            {
                "path": "public/styles.css",
                "role": "read_only",
                "language": "css",
                "content": "body { font-family: sans-serif; }",
                "includeInPrompt": True,
                "requiredInSubmission": False,
                "preserve": True,
            },
        ],
        "submissionRules": {
            "mode": "full_editable_file",
            "editablePaths": ["views/index.pug"],
        },
        "runtime": {
            "environment": "node",
            "testRunner": "jest",
            "templateEngine": "pug",
            "domEnvironment": "jsdom",
            "totalTimeoutMs": 4000,
        },
        "promptPolicy": {
            "showInstructions": True,
            "showEditableFiles": True,
            "showReadOnlyFiles": True,
            "showTests": False,
            "showPointValues": False,
            "showEvaluatorType": False,
        },
        "tests": [
            {
                "id": "render-list",
                "name": "renders todo list",
                "framework": "jest",
                "path": "tests/render-list.test.js",
                "source": test_source,
                "points": 10,
                "visibility": "hidden",
                "timeoutMs": timeout_ms,
                "isolation": "fresh_process",
                "async": False,
                "mutatesGlobals": False,
            }
        ],
        "scoring": {
            "mode": "test_all_or_nothing",
            "maximumPoints": 10,
            "activationStatus": "ready",
        },
        "metadata": {},
    }


PASSING_TEST_SOURCE = """
const fs = require("fs");
const path = require("path");
const pug = require("pug");
const { JSDOM } = require("jsdom");

test("renders todo items from locals", () => {
  const html = pug.compileFile(path.join(process.cwd(), "views/index.pug"))({
    todoList: ["Milk", "Eggs"]
  });
  const dom = new JSDOM(html);
  const items = [...dom.window.document.querySelectorAll("li")].map((node) => node.textContent.trim());
  fs.writeFileSync(path.join(process.cwd(), "FEEDBACK"), "Rendered " + items.length + " items.");
  expect(items).toEqual(["Milk", "Eggs"]);
});
""".strip()


FAILING_TEST_SOURCE = """
const path = require("path");
const pug = require("pug");
const { JSDOM } = require("jsdom");

test("fails when rendered output is wrong", () => {
  const html = pug.compileFile(path.join(process.cwd(), "views/index.pug"))({
    todoList: ["Milk", "Eggs"]
  });
  const dom = new JSDOM(html);
  const items = [...dom.window.document.querySelectorAll("li")].map((node) => node.textContent.trim());
  expect(items).toEqual(["Milk", "Bread"]);
});
""".strip()


TIMEOUT_TEST_SOURCE = """
test("times out", async () => {
  await new Promise(() => {});
});
""".strip()


@unittest.skipUnless(node_runtime_available()[0], node_runtime_available()[1] or "Node runtime unavailable")
class NodeJestPugEvaluatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_node_evaluator_dependencies()

    def test_pug_validation_accepts_complete_file(self) -> None:
        problem = Problem(
            title="Pug Demo",
            category="templates",
            difficulty="easy",
            language="pug",
            description="Render a list.",
            starter_code="p Placeholder",
            required_file="views/index.pug",
            required_function="",
            problem_key="pug-demo",
            problem_type=NODE_EVALUATOR_TYPE,
            raw_definition_json=json.dumps(build_node_problem_definition(PASSING_TEST_SOURCE)),
        )

        validation_result = validate_universal_submission(problem, PASSING_PUG_SOURCE)

        self.assertTrue(validation_result.is_valid)
        self.assertEqual(validation_result.code, PASSING_PUG_SOURCE.strip())

    def test_pug_validation_rejects_invalid_syntax(self) -> None:
        problem = Problem(
            title="Pug Demo",
            category="templates",
            difficulty="easy",
            language="pug",
            description="Render a list.",
            starter_code="p Placeholder",
            required_file="views/index.pug",
            required_function="",
            problem_key="pug-demo",
            problem_type=NODE_EVALUATOR_TYPE,
            raw_definition_json=json.dumps(build_node_problem_definition(PASSING_TEST_SOURCE)),
        )

        validation_result = validate_universal_submission(problem, BROKEN_PUG_SOURCE)

        self.assertFalse(validation_result.is_valid)
        self.assertIn("invalid Pug syntax", validation_result.error_message)

    def test_missing_editable_file_heading_is_rejected(self) -> None:
        problem = Problem(
            title="Pug Demo",
            category="templates",
            difficulty="easy",
            language="pug",
            description="Render a list.",
            starter_code="p Placeholder",
            required_file="views/index.pug",
            required_function="",
            problem_key="pug-demo",
            problem_type=NODE_EVALUATOR_TYPE,
            raw_definition_json=json.dumps(build_node_problem_definition(PASSING_TEST_SOURCE)),
        )

        validation_result = validate_universal_submission(
            problem,
            "views/index.pug\nul\n  li Item",
        )

        self.assertFalse(validation_result.is_valid)
        self.assertIn("filename heading", validation_result.error_message)

    def test_extra_submitted_file_heading_is_rejected(self) -> None:
        problem = Problem(
            title="Pug Demo",
            category="templates",
            difficulty="easy",
            language="pug",
            description="Render a list.",
            starter_code="p Placeholder",
            required_file="views/index.pug",
            required_function="",
            problem_key="pug-demo",
            problem_type=NODE_EVALUATOR_TYPE,
            raw_definition_json=json.dumps(build_node_problem_definition(PASSING_TEST_SOURCE)),
        )

        validation_result = validate_universal_submission(
            problem,
            "views/index.pug:\nul\n  li Item\n\nserver.js:\nmodule.exports = {};",
        )

        self.assertFalse(validation_result.is_valid)
        self.assertIn("filename heading", validation_result.error_message)

    def test_workspace_preserves_read_only_files(self) -> None:
        definition = build_node_problem_definition(PASSING_TEST_SOURCE)

        workspace = create_node_workspace(definition, PASSING_PUG_SOURCE)
        try:
            self.assertEqual(
                (workspace.root_path / "views/index.pug").read_text(encoding="utf-8"),
                PASSING_PUG_SOURCE,
            )
            self.assertEqual(
                (workspace.root_path / "server.js").read_text(encoding="utf-8"),
                "module.exports = {};",
            )
            self.assertEqual(
                (workspace.root_path / "public/styles.css").read_text(encoding="utf-8"),
                "body { font-family: sans-serif; }",
            )
        finally:
            workspace.cleanup()

    def test_evaluator_runs_passing_jest_test(self) -> None:
        definition = build_node_problem_definition(PASSING_TEST_SOURCE)

        result = evaluate_node_jest_pug_problem(definition, PASSING_PUG_SOURCE)
        execution_result = result.to_execution_result()

        self.assertEqual(result.status, "Accepted")
        self.assertEqual(result.score_earned, 10.0)
        self.assertEqual(result.stdout, "PASS")
        self.assertEqual(len(result.test_results), 1)
        self.assertEqual(result.test_results[0].status, "passed")
        self.assertEqual(execution_result["score_percentage"], 100.0)
        self.assertEqual(execution_result["test_results"][0]["points_earned"], 10.0)

    def test_evaluator_runs_failing_jest_test(self) -> None:
        definition = build_node_problem_definition(FAILING_TEST_SOURCE)

        result = evaluate_node_jest_pug_problem(definition, FAILING_PUG_SOURCE)

        self.assertEqual(result.status, "Wrong Answer")
        self.assertEqual(result.score_earned, 0.0)
        self.assertEqual(result.test_results[0].status, "failed")
        self.assertIsNotNone(result.stderr)

    def test_evaluator_timeout_is_captured(self) -> None:
        definition = build_node_problem_definition(TIMEOUT_TEST_SOURCE, timeout_ms=300)

        result = evaluate_node_jest_pug_problem(definition, PASSING_PUG_SOURCE)

        self.assertEqual(result.status, "Wrong Answer")
        self.assertEqual(result.test_results[0].status, "timeout")
        self.assertEqual(result.test_results[0].points_earned, 0.0)
        self.assertEqual(result.test_results[0].message, "Test execution timed out.")

    def test_dispatch_uses_node_evaluator_for_matching_type(self) -> None:
        definition = build_node_problem_definition(PASSING_TEST_SOURCE)

        class FakeEvaluationResult:
            def to_execution_result(self) -> dict:
                return {"status": "Accepted"}

        with patch(
            "app.main.evaluate_node_jest_pug_problem",
            return_value=FakeEvaluationResult(),
        ) as mocked_evaluator:
            response = evaluate_universal_problem(definition, PASSING_PUG_SOURCE)

        mocked_evaluator.assert_called_once_with(definition, PASSING_PUG_SOURCE)
        self.assertEqual(response["status"], "Accepted")
