"""
browser_qunit_evaluator.py
============================================================
WHAT THIS FILE DOES (plain English):

This file grades HTML/CSS/JavaScript submissions by actually opening
them in a real (invisible) browser and checking what's really there --
not by reading the text of the file.

THE FLOW, STEP BY STEP:

1. BUILD A TEMP WORKSPACE (create_browser_workspace)
   Copies the problem's locked files, and drops the AI's submitted
   code into the one editable file, inside a throwaway temp folder.

2. START A MINI LOCAL WEB SERVER (_start_workspace_http_server)
   Browsers behave differently when loading a file straight off disk
   vs loading it through a real URL. So instead of opening the file
   directly, this spins up a tiny local web server (just for this one
   grading run) so the browser loads it the same way a normal website
   would load. It shuts down and gets deleted right after.

3. OPEN THE BROWSER (_evaluate_single_hidden_test)
   Launches an invisible Chromium browser (Playwright), loads the
   AI's page through that local server, then injects two more scripts
   into that SAME already-loaded page:
     - the QUnit testing tool
     - the one hidden test question for this check
   Because they're injected AFTER the page loads, they can see the
   real, live version of what the browser actually built.

4. QUNIT RUNS THE TEST (still inside _evaluate_single_hidden_test)
   QUnit asks its real question about the page and reports back
   pass / fail / error / timeout. This file listens for that answer
   using a small "bridge" script (BRIDGE_SCRIPT below).

5. REPEAT FOR EVERY HIDDEN TEST, THEN ADD IT ALL UP
   (evaluate_browser_qunit_problem)
   Runs step 3-4 once per hidden test, adds up the points, and turns
   that into one final score + one final status (Accepted / Wrong
   Answer / Time Limit Exceeded / Runtime Error).

ANALOGY: grading an exam.
  - one hidden QUnit test  = one exam question
  - evaluate_browser_qunit_problem() = grading the whole exam
  - the score/status returned = the final grade on that one paper

PLAYWRIGHT vs QUNIT -- who does what:
  Playwright = just opens the browser and loads/injects things.
               It does NOT judge right or wrong.
  QUnit      = actually inspects the page and decides pass/fail.
               This is where real grading logic lives.
============================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.problem_loader import _is_safe_relative_path


# Where the local copy of the QUnit testing tool lives on disk.
# "Local" matters -- we're not downloading QUnit from the internet each
# time, it's vendored (stored) right in the project.
VENDOR_QUNIT_DIR = Path(__file__).resolve().parent.parent / "vendor" / "qunit"
QUNIT_JS_PATH = VENDOR_QUNIT_DIR / "qunit.js"
QUNIT_CSS_PATH = VENDOR_QUNIT_DIR / "qunit.css"

# BRIDGE_SCRIPT: a small piece of JavaScript that gets injected into the
# browser page. Its only job is to sit and listen for QUnit's own events
# ("a test just finished", "all tests are done") and store the results
# somewhere Python can read them back out afterward (via page.evaluate()).
# Think of it as a translator standing between QUnit (inside the browser)
# and this Python file (outside the browser).
BRIDGE_SCRIPT = """
window.__AICodeArenaBridge = {
  done: false,
  testResults: [],
};

window.QUnit.config.autostart = false;
window.QUnit.on("testEnd", function (result) {
  window.__AICodeArenaBridge.testResults.push({
    name: result.name,
    total: result.total,
    failed: result.failed,
    passed: result.passed,
    runtimeError: result.runtimeError,
    assertions: result.assertions,
    duration: result.duration,
  });
});
window.QUnit.on("runEnd", function () {
  window.__AICodeArenaBridge.done = true;
});
"""

# CSS_TEST_SETUP_SCRIPT: extra JavaScript that ONLY runs for CSS problems.
# Before grading starts, this peeks at the browser's own parsed CSS
# (document.styleSheets) to sanity-check that the stylesheet actually
# loaded and is readable, and records some debug info in case something
# goes wrong. This is diagnostic/debugging code -- a sign this CSS path
# is still being actively tested and refined.
CSS_TEST_SETUP_SCRIPT = """
window.__AICodeArenaCssDiagnostics = {
  styleSheetCount: document.styleSheets.length,
  firstHref: null,
  firstCssRulesLength: null,
  boardRulePresent: false,
  cssRulesReadable: false,
  setupError: null,
};

(function () {
  try {
    if (
      typeof CSSRuleList !== "undefined" &&
      typeof Symbol !== "undefined" &&
      Symbol.iterator &&
      !CSSRuleList.prototype[Symbol.iterator]
    ) {
      CSSRuleList.prototype[Symbol.iterator] = Array.prototype[Symbol.iterator];
    }

    const firstStyleSheet = document.styleSheets[0];
    if (!firstStyleSheet) {
      return;
    }

    window.__AICodeArenaCssDiagnostics.firstHref = firstStyleSheet.href;

    const cssRules = firstStyleSheet.cssRules;
    const cssRulesArray = Array.from(cssRules);

    window.__AICodeArenaCssDiagnostics.cssRulesReadable = true;
    window.__AICodeArenaCssDiagnostics.firstCssRulesLength = cssRulesArray.length;
    window.__AICodeArenaCssDiagnostics.boardRulePresent = cssRulesArray.some(function (rule) {
      return rule.selectorText === "#board";
    });
  } catch (error) {
    window.__AICodeArenaCssDiagnostics.setupError = error && error.message
      ? error.message
      : String(error);
  }
})();
"""


# One BrowserTestResult = the graded outcome of ONE hidden test question.
# (This is what eventually becomes one row in the EvaluationTestResult table.)
@dataclass
class BrowserTestResult:
    test_id: str
    test_name: str
    status: str
    points_possible: float
    points_earned: float
    message: Optional[str]
    assertions: List[Dict[str, Any]] = field(default_factory=list)
    console_errors: List[str] = field(default_factory=list)
    page_errors: List[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    def public_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "name": self.test_name,
            "status": self.status,
            "points_earned": self.points_earned,
            "points_possible": self.points_possible,
            "message": self.message,
            "assertions": self.assertions,
            "console_errors": self.console_errors,
            "page_errors": self.page_errors,
            "diagnostics": self.diagnostics,
            "duration_ms": self.duration_ms,
        }


# BrowserEvaluationResult = the FINAL combined outcome for the whole
# submission -- every test's result added up into one score + one status.
# (This is what becomes one row in the EvaluationResult table.)
@dataclass
class BrowserEvaluationResult:
    status: str
    score_earned: float
    score_possible: float
    score_percentage: float
    test_results: List[BrowserTestResult]
    stdout: Optional[str]
    stderr: Optional[str]
    duration_ms: int

    def to_execution_result(self) -> dict:
        return {
            "status": self.status,
            "score_earned": self.score_earned,
            "score_possible": self.score_possible,
            "score_percentage": self.score_percentage,
            "test_results": [
                test_result.public_dict() for test_result in self.test_results
            ],
            "stdout": self.stdout,
            "stderr": self.stderr,
            "compile_output": None,
            "time": f"{self.duration_ms / 1000:.3f}",
            "memory": None,
            "duration_ms": self.duration_ms,
        }


# BrowserWorkspace = everything needed for ONE grading run: the temp
# folder holding the AI's code, and the little local web server that
# serves it so the browser can load it like a real URL.
@dataclass
class BrowserWorkspace:
    temporary_directory: tempfile.TemporaryDirectory
    root_path: Path
    entry_file_path: Path
    editable_file_path: Path
    qunit_js_path: Path
    qunit_css_path: Path
    base_url: Optional[str] = None
    entry_url: Optional[str] = None
    http_server: Optional[ThreadingHTTPServer] = None
    server_thread: Optional[threading.Thread] = None

    # Starts the local mini web server for this workspace, if it isn't
    # already running. This is what lets the browser load the AI's page
    # through a real http:// URL instead of a raw file on disk.
    def ensure_http_server(self) -> None:
        if self.http_server is not None and self.server_thread is not None:
            return

        http_server, server_thread, base_url = _start_workspace_http_server(
            self.root_path
        )
        self.http_server = http_server
        self.server_thread = server_thread
        self.base_url = base_url
        relative_entry_path = self.entry_file_path.relative_to(self.root_path)
        self.entry_url = f"{base_url}/{relative_entry_path.as_posix()}"

    # Shuts the local server down and deletes the temp folder. Runs after
    # grading finishes so nothing from this run is left behind.
    def cleanup(self) -> None:
        try:
            if self.http_server is not None:
                self.http_server.shutdown()
                self.http_server.server_close()
        finally:
            if self.server_thread is not None:
                self.server_thread.join(timeout=5)
            self.temporary_directory.cleanup()


class _QuietWorkspaceRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


# Spins up a real (but tiny, local-only) web server that serves whatever
# folder you point it at, on a random free port on this machine. This is
# literally what makes "loading the AI's page in a browser" work like a
# normal website load instead of a raw file open.
def _start_workspace_http_server(root_path: Path) -> Tuple[ThreadingHTTPServer, threading.Thread, str]:
    handler = partial(_QuietWorkspaceRequestHandler, directory=str(root_path))
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = int(http_server.server_address[1])
    server_thread = threading.Thread(
        target=http_server.serve_forever,
        name=f"aicodearena-workspace-{port}",
        daemon=True,
    )
    server_thread.start()
    return http_server, server_thread, f"http://127.0.0.1:{port}"


def get_qunit_asset_paths() -> Tuple[Path, Path]:
    return QUNIT_JS_PATH, QUNIT_CSS_PATH


# Sanity-check function: is Playwright installed, and can it actually
# launch a real Chromium browser on this machine right now?
def playwright_runtime_available() -> Tuple[bool, Optional[str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright is not installed."

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
    except Exception as error:  # pragma: no cover - depends on local Chromium state
        return False, str(error)

    return True, None


def localhost_http_server_available() -> Tuple[bool, Optional[str]]:
    try:
        temporary_directory = tempfile.TemporaryDirectory()
        try:
            http_server, server_thread, _ = _start_workspace_http_server(
                Path(temporary_directory.name)
            )
            http_server.shutdown()
            http_server.server_close()
            server_thread.join(timeout=5)
        finally:
            temporary_directory.cleanup()
    except Exception as error:  # pragma: no cover - depends on local sandbox/runtime
        return False, str(error)

    return True, None


def _ensure_local_qunit_assets_exist() -> None:
    if not QUNIT_JS_PATH.exists() or not QUNIT_CSS_PATH.exists():
        raise ValueError("Local QUnit assets are missing from backend/vendor/qunit.")


def _get_single_editable_path(definition: dict) -> str:
    editable_paths = definition["submissionRules"]["editablePaths"]

    if len(editable_paths) != 1:
        raise ValueError("This MVP supports exactly one editable file.")

    editable_path = editable_paths[0]

    if not _is_safe_relative_path(editable_path):
        raise ValueError("Universal problem contains an unsafe editable path.")

    return editable_path


# ============================================================
# THIS IS "STEP 1" FROM THE TOP SUMMARY -- BUILD THE TEMP WORKSPACE.
#
# In plain English: take the problem's locked files (like index.html)
# AND the AI's submitted answer (like styles.css), and physically write
# them into a fresh, empty, throwaway folder on disk -- so grading this
# submission can never touch or mess up anything else.
# ============================================================
def create_browser_workspace(definition: dict, submitted_content: str) -> BrowserWorkspace:
    _ensure_local_qunit_assets_exist()

    editable_path = _get_single_editable_path(definition)
    temporary_directory = tempfile.TemporaryDirectory()
    root_path = Path(temporary_directory.name)
    entry_file = definition["runtime"]["entryFile"]

    if not _is_safe_relative_path(entry_file):
        temporary_directory.cleanup()
        raise ValueError("Universal problem contains an unsafe entry file path.")

    # Write every file the problem defines into the temp folder.
    # If it's the ONE editable file -> write the AI's submitted answer.
    # Otherwise -> write the locked starter content as-is (untouched).
    for file_definition in definition["files"]:
        file_path = file_definition["path"]
        if not _is_safe_relative_path(file_path):
            temporary_directory.cleanup()
            raise ValueError("Universal problem contains an unsafe file path.")

        target_path = root_path / file_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if file_definition["role"] == "editable":
            target_path.write_text(submitted_content, encoding="utf-8")
            continue

        content = file_definition.get("content")
        if content is None:
            continue

        target_path.write_text(content, encoding="utf-8")

    # Also copy the QUnit tool itself into the workspace, so the browser
    # can load it locally instead of needing internet access.
    vendor_target = root_path / "_aicodearena_vendor" / "qunit"
    vendor_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(QUNIT_JS_PATH, vendor_target / "qunit.js")
    shutil.copy2(QUNIT_CSS_PATH, vendor_target / "qunit.css")
    return BrowserWorkspace(
        temporary_directory=temporary_directory,
        root_path=root_path,
        entry_file_path=root_path / entry_file,
        editable_file_path=root_path / editable_path,
        qunit_js_path=vendor_target / "qunit.js",
        qunit_css_path=vendor_target / "qunit.css",
    )


# Looks at how a single test came back and decides which bucket it falls
# into: did it time out, crash with a syntax error, crash some other way,
# fail a real check, or actually pass.
def _classify_test_status(
    bridge_result: Optional[dict],
    page_errors: List[str],
    timed_out: bool,
) -> str:
    if timed_out:
        return "timeout"

    if page_errors and any("syntaxerror" in error.lower() for error in page_errors):
        return "syntax_error"

    if bridge_result is None:
        return "runtime_error" if page_errors else "setup_error"

    if bridge_result.get("runtimeError") is not None:
        runtime_error = bridge_result["runtimeError"]
        if "syntaxerror" in str(runtime_error.get("name", "")).lower():
            return "syntax_error"
        return "runtime_error"

    if bridge_result.get("failed", 0) > 0:
        return "failed"

    return "passed"


# Builds a human-readable explanation of WHY a test failed (used for the
# "message" field you'd see on a failed test result).
def _summarize_message(
    bridge_result: Optional[dict],
    console_errors: List[str],
    page_errors: List[str],
    timed_out: bool,
) -> Optional[str]:
    if timed_out:
        return "Test execution timed out."

    if bridge_result:
        for assertion in bridge_result.get("assertions", []):
            if not assertion.get("result", True):
                message = assertion.get("message") or "Assertion failed."
                actual = assertion.get("actual")
                expected = assertion.get("expected")
                return f"{message} Expected {expected!r}, got {actual!r}."

        runtime_error = bridge_result.get("runtimeError")
        if runtime_error:
            return runtime_error.get("message") or "Runtime error."

    if page_errors:
        return page_errors[0]

    if console_errors:
        return console_errors[0]

    return None


# Once EVERY hidden test has a result, this decides the ONE overall
# status for the whole submission (this is the "whole exam grade" step).
def _build_overall_status(test_results: List[BrowserTestResult], total_timed_out: bool) -> str:
    if total_timed_out:
        return "Time Limit Exceeded"

    total_points = sum(result.points_possible for result in test_results)
    earned_points = sum(result.points_earned for result in test_results)

    if total_points > 0 and earned_points == total_points:
        return "Accepted"

    if any(
        result.status in {"runtime_error", "syntax_error", "setup_error"}
        for result in test_results
    ) and not any(
        result.status in {"passed", "failed", "timeout"} for result in test_results
    ):
        return "Runtime Error"

    return "Wrong Answer"


def _build_stderr(test_results: List[BrowserTestResult], total_timed_out: bool) -> Optional[str]:
    if total_timed_out:
        return "Total browser evaluation timed out."

    messages = []
    for result in test_results:
        if result.status != "passed" and result.message:
            messages.append(f"{result.test_name}: {result.message}")

    return "\n".join(messages) if messages else None


# ============================================================
# THIS IS "STEP 3 + 4" FROM THE TOP SUMMARY -- THE CORE FUNCTION.
#
# In plain English: open ONE invisible browser tab, load the AI's page
# into it, sneak in QUnit + this one hidden test, let it run, and report
# back exactly what happened. This runs ONCE PER hidden test question.
# ============================================================
def _evaluate_single_hidden_test(
    playwright,
    workspace: BrowserWorkspace,
    runtime_definition: dict,
    test_definition: dict,
    evaluator_type: Optional[str] = None,
) -> BrowserTestResult:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    workspace.ensure_http_server()
    # Open an invisible (headless) Chromium browser instance.
    browser = playwright.chromium.launch(headless=runtime_definition.get("headless", True))
    context = browser.new_context(
        viewport=runtime_definition.get("viewport"),
    )
    # Security guard: block the page from loading anything off the real
    # internet -- it can ONLY talk to this workspace's own local server.
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
    console_errors: List[str] = []
    page_errors: List[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    test_started_at = time.perf_counter()
    bridge_result = None
    timed_out = False
    current_stage = "initializing"
    css_diagnostics: Dict[str, Any] = {}

    try:
        # 1) Actually load the AI's page -- like opening a normal tab.
        current_stage = "page.goto"
        page.goto(
            workspace.entry_url,
            wait_until=runtime_definition.get("waitFor", "load"),
            timeout=runtime_definition.get("setupTimeoutMs", 10000),
        )
        if evaluator_type == "browser_qunit_css":
            # CSS-only extra step: wait until the stylesheet is really
            # loaded, then collect some debug info about it.
            current_stage = "waiting_for_stylesheet"
            page.wait_for_function(
                """
                () => (
                    document.styleSheets.length > 0 &&
                    document.styleSheets[0].href !== null &&
                    document.styleSheets[0].href.includes("styles.css")
                )
                """,
                timeout=runtime_definition.get("setupTimeoutMs", 10000),
            )
            current_stage = "collecting_css_diagnostics"
            page.add_script_tag(content=CSS_TEST_SETUP_SCRIPT)
            css_diagnostics = page.evaluate(
                """() => ({
                    locationHref: document.location.href,
                    styleSheetCount: document.styleSheets.length,
                    firstStyleSheetHref: document.styleSheets[0] ? document.styleSheets[0].href : null,
                    firstCssRulesLength: window.__AICodeArenaCssDiagnostics
                        ? window.__AICodeArenaCssDiagnostics.firstCssRulesLength
                        : null,
                    firstSelectorTexts: (() => {
                        try {
                            return document.styleSheets[0]
                                ? Array.from(document.styleSheets[0].cssRules).map((rule) => rule.selectorText || null)
                                : [];
                        } catch (error) {
                            return ["<cssRules unreadable: " + (error && error.message ? error.message : String(error)) + ">"];
                        }
                    })(),
                    cssRulesReadable: window.__AICodeArenaCssDiagnostics
                        ? window.__AICodeArenaCssDiagnostics.cssRulesReadable
                        : false,
                    boardRulePresent: window.__AICodeArenaCssDiagnostics
                        ? window.__AICodeArenaCssDiagnostics.boardRulePresent
                        : false,
                    cssRuleListType: typeof CSSRuleList,
                    cssRuleListIteratorPresent: Boolean(
                        typeof CSSRuleList !== "undefined" &&
                        typeof Symbol !== "undefined" &&
                        Symbol.iterator &&
                        CSSRuleList.prototype[Symbol.iterator]
                    ),
                    qunitTypeBeforeRuntime: typeof window.QUnit,
                    qunitTestTypeBeforeRuntime: typeof (window.QUnit && window.QUnit.test),
                    qunitStartTypeBeforeRuntime: typeof (window.QUnit && window.QUnit.start),
                    setupError: window.__AICodeArenaCssDiagnostics
                        ? window.__AICodeArenaCssDiagnostics.setupError
                        : null,
                })"""
            )
            if css_diagnostics.get("setupError"):
                page_errors.append(
                    "CSS setup error: " + str(css_diagnostics["setupError"])
                )
            if not css_diagnostics.get("cssRulesReadable", False):
                page_errors.append("CSS setup error: Unable to read styles.css cssRules.")

        # 2) THIS is the "injection" step -- add the QUnit tool itself
        #    into the page that's already loaded and sitting there.
        current_stage = "injecting_qunit_runtime"
        page.add_script_tag(path=str(workspace.qunit_js_path))
        if evaluator_type == "browser_qunit_css":
            css_diagnostics["qunitTypeAfterRuntime"] = page.evaluate("typeof window.QUnit")
            css_diagnostics["qunitTestTypeAfterRuntime"] = page.evaluate(
                "typeof (window.QUnit && window.QUnit.test)"
            )
            css_diagnostics["qunitStartTypeAfterRuntime"] = page.evaluate(
                "typeof (window.QUnit && window.QUnit.start)"
            )
        # 3) Inject the "bridge" script (the translator described above).
        current_stage = "injecting_bridge"
        page.add_script_tag(content=BRIDGE_SCRIPT)
        # 4) Inject the ACTUAL hidden test question for this specific check.
        current_stage = "injecting_hidden_test"
        page.add_script_tag(content=test_definition["source"])
        # 5) Now that everything's injected, tell QUnit to actually run.
        current_stage = "starting_qunit"
        page.evaluate("() => { window.QUnit.start(); }")
        # 6) Wait for the bridge script to report "done".
        current_stage = "waiting_for_qunit_completion"
        page.wait_for_function(
            "window.__AICodeArenaBridge && window.__AICodeArenaBridge.done === true",
            timeout=test_definition["timeoutMs"],
        )
        # 7) Pull the actual pass/fail result back out of the browser.
        current_stage = "collecting_bridge_results"
        bridge_data = page.evaluate("window.__AICodeArenaBridge")
        if bridge_data.get("testResults"):
            bridge_result = bridge_data["testResults"][0]
    except PlaywrightTimeoutError:
        timed_out = True
    except Exception as error:  # pragma: no cover - behavior depends on browser runtime
        error_message = str(error)
        if "Timeout" in error_message or "timed out" in error_message.lower():
            timed_out = True
        else:
            page_errors.append(f"Stage {current_stage}: {error_message}")
    finally:
        # Always close the browser tab/context, pass or fail or crash.
        current_stage = "cleanup"
        try:
            page.close()
        except Exception:
            pass
        try:
            context.close()
        finally:
            try:
                browser.close()
            except Exception:
                pass

    duration_ms = int((time.perf_counter() - test_started_at) * 1000)
    status = _classify_test_status(bridge_result, page_errors, timed_out)
    points_possible = float(test_definition["points"])
    points_earned = points_possible if status == "passed" else 0.0
    message = _summarize_message(bridge_result, console_errors, page_errors, timed_out)

    return BrowserTestResult(
        test_id=test_definition["id"],
        test_name=test_definition["name"],
        status=status,
        points_possible=points_possible,
        points_earned=points_earned,
        message=message,
        assertions=list(bridge_result.get("assertions", [])) if bridge_result else [],
        console_errors=console_errors,
        page_errors=page_errors,
        diagnostics={
            "stage": current_stage,
            "css": css_diagnostics,
            "runtimeError": bridge_result.get("runtimeError") if bridge_result else None,
        },
        duration_ms=duration_ms,
    )


# ============================================================
# THIS IS THE "GRADE THE WHOLE EXAM" FUNCTION -- the main entry point
# that main.py actually calls for one submission.
#
# In plain English: build the workspace once, then run EVERY hidden
# test one at a time (calling the function above per test), add up all
# the points, and return one final score + one final status.
# ============================================================
def evaluate_browser_qunit_problem(
    definition: dict,
    submitted_content: str,
) -> BrowserEvaluationResult:
    evaluation_started_at = time.perf_counter()
    runtime_definition = definition["runtime"]
    total_timeout_ms = runtime_definition.get("totalTimeoutMs", 30000)

    from playwright.sync_api import sync_playwright

    # Build the temp workspace ONCE for this whole submission.
    workspace = create_browser_workspace(definition, submitted_content)
    test_results: List[BrowserTestResult] = []
    total_timed_out = False

    try:
        with sync_playwright() as playwright:
            # Loop through EVERY hidden test for this problem, one at a
            # time, and grade each one individually.
            for test_definition in definition["tests"]:
                elapsed_ms = int((time.perf_counter() - evaluation_started_at) * 1000)
                if elapsed_ms >= total_timeout_ms:
                    total_timed_out = True
                    break

                test_result = _evaluate_single_hidden_test(
                    playwright,
                    workspace,
                    runtime_definition,
                    test_definition,
                    definition.get("evaluatorType"),
                )
                test_results.append(test_result)
    finally:
        # Always clean up the temp folder + local server, no matter what.
        workspace.cleanup()

    duration_ms = int((time.perf_counter() - evaluation_started_at) * 1000)
    score_possible = float(sum(float(test["points"]) for test in definition["tests"]))
    score_earned = float(sum(result.points_earned for result in test_results))
    score_percentage = (score_earned / score_possible * 100.0) if score_possible else 0.0
    status = _build_overall_status(test_results, total_timed_out)

    if status == "Accepted":
        stdout = "PASS"
    else:
        stdout = f"Score: {score_earned:g}/{score_possible:g}"

    return BrowserEvaluationResult(
        status=status,
        score_earned=score_earned,
        score_possible=score_possible,
        score_percentage=score_percentage,
        test_results=test_results,
        stdout=stdout,
        stderr=_build_stderr(test_results, total_timed_out),
        duration_ms=duration_ms,
    )
