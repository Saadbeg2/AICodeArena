import copy
import json
import os
from pathlib import Path
import socket
import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.browser_qunit_evaluator import (
    create_browser_workspace,
    evaluate_browser_qunit_problem,
    get_qunit_asset_paths,
    localhost_http_server_available,
    playwright_runtime_available,
)
from app.main import (
    CompetitionRequest,
    ModelRunRequest,
    get_competition_run,
    run_competition,
    run_model_solution,
)
from app.models import Problem
from app.legacy.mock_models import (
    MOCK_NOTABLE_QUOTES_BAD_RESPONSE,
    MOCK_NOTABLE_QUOTES_GOOD_RESPONSE,
)
from app.seed import seed_database
from app.submission_validator import validate_javascript_full_file_submission
from tests.provider_fixtures import (
    NOTABLE_QUOTES_ACCEPTED_AND_FAILED,
    REAL_GEMINI,
    REAL_GROQ,
    STARTING_LINEUP_ACCEPTED_AND_FAILED,
    TIC_TAC_TOE_ACCEPTED_AND_FAILED,
    build_generate_solution_side_effect,
)


def _browser_definition() -> dict:
    return {
        "schemaVersion": "1.0",
        "id": "browser-test-problem",
        "title": "Browser Test Problem",
        "description": "Synthetic browser assignment for evaluator tests.",
        "course": "COSC 4398",
        "sourcePlatform": "custom",
        "assignmentType": "html-dom",
        "evaluatorType": "browser_qunit_html",
        "language": "html",
        "technologies": ["HTML", "QUnit"],
        "instructions": {
            "studentPrompt": "Return the complete index.html file."
        },
        "files": [
            {
                "path": "index.html",
                "role": "editable",
                "language": "html",
                "content": "<!DOCTYPE html><html><head><title>Demo</title></head><body><div id='app'></div></body></html>",
                "includeInPrompt": True,
                "requiredInSubmission": True,
                "preserve": False,
            },
            {
                "path": "styles.css",
                "role": "read_only",
                "language": "css",
                "content": "body { color: black; }",
                "includeInPrompt": False,
                "requiredInSubmission": False,
                "preserve": True,
            },
            {
                "path": "optional.txt",
                "role": "asset",
                "language": "text",
                "content": None,
                "includeInPrompt": False,
                "requiredInSubmission": False,
                "preserve": True,
            },
        ],
        "submissionRules": {
            "mode": "full_editable_file",
            "editablePaths": ["index.html"],
        },
        "runtime": {
            "environment": "browser",
            "entryFile": "index.html",
            "browserEngine": "Chromium",
            "headless": True,
            "network": "disabled",
            "processIsolation": "fresh_environment",
            "testIsolation": "fresh_page",
            "waitFor": "load",
            "viewport": {"width": 1280, "height": 720},
            "setupTimeoutMs": 5000,
            "individualTestTimeoutMs": 2000,
            "totalTimeoutMs": 10000,
        },
        "promptPolicy": {
            "showInstructions": True,
            "showEditableFiles": True,
            "showReadOnlyFiles": False,
            "showTests": False,
            "showPointValues": False,
            "showEvaluatorType": False,
        },
        "tests": [
            {
                "id": "pass-test",
                "name": "Pass test",
                "framework": "qunit",
                "path": "tests/pass.js",
                "source": "QUnit.test('Pass test', function (assert) { assert.ok(document.querySelector('#app') !== null, 'App exists'); });",
                "points": 2,
                "visibility": "hidden",
                "timeoutMs": 2000,
                "isolation": "fresh_page",
                "async": False,
                "mutatesGlobals": False,
            }
        ],
        "scoring": {
            "mode": "test_all_or_nothing",
            "maximumPoints": 2,
            "activationStatus": "ready",
        },
        "metadata": {},
    }


class BrowserWorkspaceTests(unittest.TestCase):
    def _require_local_http_server(self) -> None:
        available, reason = localhost_http_server_available()
        if not available:
            self.skipTest(reason or "Local HTTP server unavailable")

    def test_workspace_writes_read_only_files(self) -> None:
        definition = _browser_definition()
        workspace = create_browser_workspace(
            definition,
            "<!DOCTYPE html><html><head></head><body>Hi</body></html>",
        )

        try:
            self.assertTrue((workspace.root_path / "styles.css").exists())
        finally:
            workspace.cleanup()

    def test_workspace_replaces_editable_file_with_submitted_content(self) -> None:
        definition = _browser_definition()
        submitted = "<!DOCTYPE html><html><head></head><body>Submitted</body></html>"
        workspace = create_browser_workspace(definition, submitted)

        try:
            contents = (workspace.root_path / "index.html").read_text(encoding="utf-8")
            self.assertEqual(contents, submitted)
        finally:
            workspace.cleanup()

    def test_workspace_starts_local_http_server(self) -> None:
        self._require_local_http_server()
        definition = _browser_definition()
        workspace = create_browser_workspace(
            definition,
            "<!DOCTYPE html><html><head></head><body>Hi</body></html>",
        )

        try:
            workspace.ensure_http_server()
            self.assertTrue(workspace.entry_url.startswith("http://127.0.0.1:"))
            self.assertTrue(workspace.server_thread.is_alive())
        finally:
            workspace.cleanup()

    def test_workspace_server_stops_on_cleanup(self) -> None:
        self._require_local_http_server()
        definition = _browser_definition()
        workspace = create_browser_workspace(
            definition,
            "<!DOCTYPE html><html><head></head><body>Hi</body></html>",
        )
        workspace.ensure_http_server()
        port = workspace.http_server.server_address[1]

        workspace.cleanup()

        self.assertFalse(workspace.server_thread.is_alive())
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
            probe_socket.settimeout(0.5)
            self.assertNotEqual(probe_socket.connect_ex(("127.0.0.1", port)), 0)

    def test_workspace_skips_null_optional_files(self) -> None:
        definition = _browser_definition()
        workspace = create_browser_workspace(
            definition,
            "<!DOCTYPE html><html><head></head><body>Hi</body></html>",
        )

        try:
            self.assertFalse((workspace.root_path / "optional.txt").exists())
        finally:
            workspace.cleanup()

    def test_unsafe_paths_are_rejected(self) -> None:
        definition = _browser_definition()
        definition["files"][0]["path"] = "../index.html"

        with self.assertRaisesRegex(ValueError, "unsafe file path"):
            create_browser_workspace(
                definition,
                "<!DOCTYPE html><html><head></head><body>Hi</body></html>",
            )

    def test_local_qunit_assets_available(self) -> None:
        qunit_js_path, qunit_css_path = get_qunit_asset_paths()

        self.assertTrue(qunit_js_path.exists())
        self.assertTrue(qunit_css_path.exists())

    def test_notable_quotes_primary_provider_fixture_passes_format_validation(self) -> None:
        result = validate_javascript_full_file_submission(
            MOCK_NOTABLE_QUOTES_GOOD_RESPONSE
        )

        self.assertTrue(result.is_valid, result.error_message)

    def test_notable_quotes_secondary_provider_fixture_passes_format_validation(self) -> None:
        result = validate_javascript_full_file_submission(
            MOCK_NOTABLE_QUOTES_BAD_RESPONSE
        )

        self.assertTrue(result.is_valid, result.error_message)


@unittest.skipUnless(playwright_runtime_available()[0], playwright_runtime_available()[1] or "Chromium unavailable")
class BrowserEvaluatorCoreTests(unittest.TestCase):
    def test_one_passing_qunit_test_is_captured(self) -> None:
        result = evaluate_browser_qunit_problem(
            _browser_definition(),
            "<!DOCTYPE html><html><head></head><body><div id='app'></div></body></html>",
        )

        self.assertEqual(result.test_results[0].status, "passed")
        self.assertEqual(result.score_earned, 2.0)

    def test_one_failing_qunit_test_is_captured(self) -> None:
        definition = _browser_definition()
        definition["tests"][0]["source"] = (
            "QUnit.test('Fail test', function (assert) { assert.equal(1, 2, 'Numbers should match'); });"
        )
        result = evaluate_browser_qunit_problem(
            definition,
            "<!DOCTYPE html><html><head></head><body><div id='app'></div></body></html>",
        )

        self.assertEqual(result.test_results[0].status, "failed")
        self.assertEqual(result.status, "Wrong Answer")

    def test_assertion_message_is_captured(self) -> None:
        definition = _browser_definition()
        definition["tests"][0]["source"] = (
            "QUnit.test('Fail test', function (assert) { assert.equal('a', 'b', 'Letters should match'); });"
        )
        result = evaluate_browser_qunit_problem(
            definition,
            "<!DOCTYPE html><html><head></head><body><div id='app'></div></body></html>",
        )

        self.assertIn("Letters should match", result.test_results[0].message)

    def test_page_error_is_captured(self) -> None:
        definition = _browser_definition()
        submitted = "<!DOCTYPE html><html><head><script>throw new Error('boom');</script></head><body><div id='app'></div></body></html>"
        result = evaluate_browser_qunit_problem(definition, submitted)

        self.assertTrue(result.test_results[0].page_errors)

    def test_per_test_timeout_is_captured(self) -> None:
        definition = _browser_definition()
        definition["tests"][0]["timeoutMs"] = 200
        definition["tests"][0]["source"] = (
            "QUnit.test('Slow test', function (assert) { return new Promise(function () {}); });"
        )
        started_at = time.perf_counter()
        result = evaluate_browser_qunit_problem(
            definition,
            "<!DOCTYPE html><html><head></head><body><div id='app'></div></body></html>",
        )
        elapsed_seconds = time.perf_counter() - started_at

        self.assertEqual(result.test_results[0].status, "timeout")
        self.assertEqual(result.test_results[0].points_earned, 0.0)
        self.assertIn("timed out", result.test_results[0].message.lower())
        self.assertLess(elapsed_seconds, 5.0)

    def test_fresh_context_prevents_global_leakage(self) -> None:
        definition = _browser_definition()
        definition["tests"] = [
            {
                "id": "mutate",
                "name": "Mutate",
                "framework": "qunit",
                "path": "tests/mutate.js",
                "source": "QUnit.test('Mutate', function (assert) { window.leakedValue = 5; assert.ok(true, 'Mutation executed'); });",
                "points": 1,
                "visibility": "hidden",
                "timeoutMs": 2000,
                "isolation": "fresh_page",
                "async": False,
                "mutatesGlobals": True,
            },
            {
                "id": "check-clean",
                "name": "Check clean",
                "framework": "qunit",
                "path": "tests/check-clean.js",
                "source": "QUnit.test('Check clean', function (assert) { assert.strictEqual(window.leakedValue, undefined, 'Global state should not leak'); });",
                "points": 1,
                "visibility": "hidden",
                "timeoutMs": 2000,
                "isolation": "fresh_page",
                "async": False,
                "mutatesGlobals": True,
            },
        ]
        definition["scoring"]["maximumPoints"] = 2
        result = evaluate_browser_qunit_problem(
            definition,
            "<!DOCTYPE html><html><head></head><body><div id='app'></div></body></html>",
        )

        self.assertEqual(result.status, "Accepted")
        self.assertEqual(result.score_earned, 2.0)

    def test_weighted_points_calculated_correctly(self) -> None:
        definition = _browser_definition()
        definition["tests"] = [
            copy.deepcopy(definition["tests"][0]),
            copy.deepcopy(definition["tests"][0]),
        ]
        definition["tests"][0]["id"] = "pass"
        definition["tests"][0]["name"] = "Pass"
        definition["tests"][0]["points"] = 2
        definition["tests"][1]["id"] = "fail"
        definition["tests"][1]["name"] = "Fail"
        definition["tests"][1]["points"] = 3
        definition["tests"][1]["source"] = (
            "QUnit.test('Fail', function (assert) { assert.equal(1, 2, 'Mismatch'); });"
        )
        definition["scoring"]["maximumPoints"] = 5
        result = evaluate_browser_qunit_problem(
            definition,
            "<!DOCTYPE html><html><head></head><body><div id='app'></div></body></html>",
        )

        self.assertEqual(result.score_earned, 2.0)
        self.assertEqual(result.score_possible, 5.0)
        self.assertEqual(result.score_percentage, 40.0)

    def test_css_stylesheet_index_zero_is_styles_css(self) -> None:
        definition = {
            **_browser_definition(),
            "evaluatorType": "browser_qunit_css",
            "language": "css",
            "runtime": {
                **_browser_definition()["runtime"],
                "entryFile": "index.html",
            },
            "files": [
                {
                    "path": "index.html",
                    "role": "read_only",
                    "language": "html",
                    "content": (
                        "<!DOCTYPE html><html><head>"
                        "<link rel='stylesheet' href='styles.css'>"
                        "</head><body><div id='board'></div></body></html>"
                    ),
                    "includeInPrompt": False,
                    "requiredInSubmission": False,
                    "preserve": True,
                },
                {
                    "path": "styles.css",
                    "role": "editable",
                    "language": "css",
                    "content": "#board { display: grid; }",
                    "includeInPrompt": True,
                    "requiredInSubmission": True,
                    "preserve": False,
                },
            ],
            "submissionRules": {
                "mode": "full_editable_file",
                "editablePaths": ["styles.css"],
            },
        }
        workspace = create_browser_workspace(definition, "#board { display: grid; }")
        try:
            workspace.ensure_http_server()
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context()
                allowed_host_prefixes = (
                    workspace.base_url,
                    "http://127.0.0.1",
                    "http://localhost",
                )
                context.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.url.startswith(("http://", "https://"))
                    and not route.request.url.startswith(allowed_host_prefixes)
                    else route.continue_(),
                )
                page = context.new_page()
                try:
                    page.goto(workspace.entry_url, wait_until="load")
                    diagnostics = page.evaluate(
                        """() => {
                            if (document.location.protocol !== "http:") {
                                return {
                                    href: null,
                                    cssRulesLength: null,
                                    boardRulePresent: false,
                                    protocol: document.location.protocol,
                                };
                            }
                            const firstStyleSheet = document.styleSheets[0];
                            if (!firstStyleSheet) {
                                return {
                                    href: null,
                                    cssRulesLength: null,
                                    boardRulePresent: false,
                                    protocol: document.location.protocol,
                                };
                            }

                            const cssRulesArray = Array.from(firstStyleSheet.cssRules || []);
                            return {
                                protocol: document.location.protocol,
                                href: firstStyleSheet.href,
                                cssRulesLength: cssRulesArray.length,
                                boardRulePresent: cssRulesArray.some(
                                    (rule) => rule.selectorText === "#board"
                                ),
                            };
                        }"""
                    )
                    self.assertEqual(diagnostics["protocol"], "http:", diagnostics)
                    self.assertTrue(diagnostics["href"].endswith("/styles.css"), diagnostics)
                    self.assertGreater(diagnostics["cssRulesLength"], 0, diagnostics)
                    self.assertTrue(diagnostics["boardRulePresent"], diagnostics)
                finally:
                    page.close()
                    context.close()
                    browser.close()
        finally:
            workspace.cleanup()

    def test_external_requests_remain_blocked(self) -> None:
        definition = _browser_definition()
        definition["tests"][0]["source"] = (
            "QUnit.test('Network blocked', async function (assert) {"
            "  let fetchFailed = false;"
            "  try {"
            "    await fetch('https://example.com/data.json');"
            "  } catch (error) {"
            "    fetchFailed = true;"
            "  }"
            "  assert.ok(fetchFailed, 'External fetch should be blocked');"
            "});"
        )

        result = evaluate_browser_qunit_problem(
            definition,
            "<!DOCTYPE html><html><head></head><body><div id='app'></div></body></html>",
        )

        self.assertEqual(result.status, "Accepted")

    def test_total_timeout_behavior(self) -> None:
        definition = _browser_definition()
        definition["runtime"]["totalTimeoutMs"] = 1
        result = evaluate_browser_qunit_problem(
            definition,
            "<!DOCTYPE html><html><head></head><body><div id='app'></div></body></html>",
        )

        self.assertEqual(result.status, "Time Limit Exceeded")


@unittest.skipUnless(playwright_runtime_available()[0], playwright_runtime_available()[1] or "Chromium unavailable")
class BrowserUniversalIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(bind=self.engine)
        seed_database(self.engine, self.session_factory)
        self.database = self.session_factory()

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def _run_browser_model(self, problem_key: str, model_name: str) -> dict:
        response_map = {
            "starting-lineup-form": STARTING_LINEUP_ACCEPTED_AND_FAILED,
            "tic-tac-toe-board": TIC_TAC_TOE_ACCEPTED_AND_FAILED,
            "notable-quotes": NOTABLE_QUOTES_ACCEPTED_AND_FAILED,
        }[problem_key]
        with patch(
            "app.main.generate_solution",
            side_effect=build_generate_solution_side_effect(response_map),
        ):
            return run_model_solution(
                self._problem_id(problem_key),
                ModelRunRequest(model_name=model_name),
                self.database,
            )

    def _problem_id(self, problem_key: str) -> int:
        problem = self.database.scalar(select(Problem).where(Problem.problem_key == problem_key))
        return problem.id

    def _format_execution_diagnostics(self, response: dict) -> str:
        execution_result = response["execution_result"]
        lines = [
            "execution_result.status=" + repr(execution_result.get("status")),
            "execution_result.stdout=" + repr(execution_result.get("stdout")),
            "execution_result.stderr=" + repr(execution_result.get("stderr")),
            "execution_result.test_results=" + json.dumps(
                execution_result.get("test_results", []),
                indent=2,
                default=str,
            ),
        ]

        for test_result in execution_result.get("test_results", []):
            lines.extend(
                [
                    "-- test result --",
                    "test_id=" + repr(test_result.get("test_id")),
                    "status=" + repr(test_result.get("status")),
                    "message=" + repr(test_result.get("message")),
                    "points_earned=" + repr(test_result.get("points_earned")),
                    "console_errors=" + json.dumps(test_result.get("console_errors", []), indent=2, default=str),
                    "page_errors=" + json.dumps(test_result.get("page_errors", []), indent=2, default=str),
                    "assertions=" + json.dumps(test_result.get("assertions", []), indent=2, default=str),
                    "diagnostics=" + json.dumps(test_result.get("diagnostics", {}), indent=2, default=str),
                ]
            )

        return "\n".join(lines)

    def test_starting_lineup_primary_provider_scores_ten(self) -> None:
        response = self._run_browser_model("starting-lineup-form", REAL_GEMINI)

        self.assertEqual(response["execution_result"]["status"], "Accepted")
        self.assertEqual(response["execution_result"]["score_earned"], 10.0)

    def test_starting_lineup_secondary_provider_returns_wrong_answer(self) -> None:
        response = self._run_browser_model("starting-lineup-form", REAL_GROQ)

        self.assertEqual(response["execution_result"]["status"], "Wrong Answer")

    def test_tic_tac_toe_primary_provider_scores_ten(self) -> None:
        response = self._run_browser_model("tic-tac-toe-board", REAL_GEMINI)

        diagnostics = self._format_execution_diagnostics(response)
        self.assertEqual(
            response["execution_result"]["status"],
            "Accepted",
            diagnostics,
        )
        self.assertEqual(
            response["execution_result"]["score_earned"],
            10.0,
            diagnostics,
        )

    def test_tic_tac_toe_secondary_provider_returns_wrong_answer(self) -> None:
        response = self._run_browser_model("tic-tac-toe-board", REAL_GROQ)

        diagnostics = self._format_execution_diagnostics(response)
        self.assertEqual(
            response["execution_result"]["status"],
            "Wrong Answer",
            diagnostics,
        )

    def test_notable_quotes_primary_provider_scores_ten(self) -> None:
        response = self._run_browser_model("notable-quotes", REAL_GEMINI)

        self.assertEqual(response["execution_result"]["status"], "Accepted")
        self.assertEqual(response["execution_result"]["score_earned"], 10.0)

    def test_notable_quotes_secondary_provider_returns_wrong_answer(self) -> None:
        response = self._run_browser_model("notable-quotes", REAL_GROQ)

        self.assertEqual(response["execution_result"]["status"], "Wrong Answer")

    def test_run_competition_returns_score_fields(self) -> None:
        with patch(
            "app.main.generate_solution",
            side_effect=build_generate_solution_side_effect(
                STARTING_LINEUP_ACCEPTED_AND_FAILED
            ),
        ):
            response = run_competition(
                self._problem_id("starting-lineup-form"),
                CompetitionRequest(),
                self.database,
            )
            deadline = time.time() + 2.0
            while time.time() < deadline:
                with self.SessionFactory() as database:
                    response = get_competition_run(
                        self._problem_id("starting-lineup-form"),
                        response["competition_run_id"],
                        database,
                    )
                if response["status"] in {"completed", "completed_with_errors"}:
                    break
                time.sleep(0.02)
            else:
                self.fail("Timed out waiting for competition completion")

        self.assertIn("score_earned", response["results"][0])
        self.assertIn("score_possible", response["results"][0])
        self.assertIn("score_percentage", response["results"][0])

    def test_hidden_test_source_is_not_returned(self) -> None:
        response = self._run_browser_model("starting-lineup-form", REAL_GEMINI)

        self.assertNotIn("source", response["execution_result"]["test_results"][0])


if __name__ == "__main__":
    unittest.main()
