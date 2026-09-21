from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple


NODE_EVALUATOR_TYPE = "node_jest_pug_jsdom"
NODE_RUNTIME_DIRECTORY = Path(__file__).resolve().parents[1] / "node_evaluator_runtime"
REQUIRED_NODE_PACKAGES = (
    "jest",
    "jsdom",
    "pug",
    "jest-environment-jsdom",
    "jest-expect-message",
)
DEFAULT_NODE_TIMEOUT_MS = 15000


@dataclass
class NodeJestTestResult:
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


@dataclass
class NodeJestEvaluationResult:
    status: str
    score_earned: float
    score_possible: float
    score_percentage: float
    test_results: List[NodeJestTestResult]
    stdout: Optional[str]
    stderr: Optional[str]
    duration_ms: int

    def to_execution_result(self) -> dict:
        return {
            "status": self.status,
            "score_earned": self.score_earned,
            "score_possible": self.score_possible,
            "score_percentage": self.score_percentage,
            "test_results": [test_result.public_dict() for test_result in self.test_results],
            "stdout": self.stdout,
            "stderr": self.stderr,
            "compile_output": None,
            "time": f"{self.duration_ms / 1000:.3f}",
            "memory": None,
            "duration_ms": self.duration_ms,
        }


@dataclass
class NodeWorkspace:
    temporary_directory: tempfile.TemporaryDirectory
    root_path: Path
    editable_file_path: Path
    jest_config_path: Path

    def cleanup(self) -> None:
        self.temporary_directory.cleanup()


def _node_runtime_environment() -> dict:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "AICODEARENA_ADMIN_KEY",
        }
    }
    environment["HTTP_PROXY"] = ""
    environment["HTTPS_PROXY"] = ""
    environment["ALL_PROXY"] = ""
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    environment["NODE_PATH"] = str(NODE_RUNTIME_DIRECTORY / "node_modules")
    environment["CI"] = "true"
    return environment


def _node_runtime_paths() -> Tuple[Path, Path, Path]:
    node_modules_path = NODE_RUNTIME_DIRECTORY / "node_modules"
    jest_cli_path = node_modules_path / "jest" / "bin" / "jest.js"
    package_json_path = NODE_RUNTIME_DIRECTORY / "package.json"
    return node_modules_path, jest_cli_path, package_json_path


def node_runtime_available() -> Tuple[bool, Optional[str]]:
    if shutil.which("node") is None:
        return False, "Node.js is not installed."

    if shutil.which("npm") is None:
        return False, "npm is not installed."

    _, _, package_json_path = _node_runtime_paths()
    if not package_json_path.exists():
        return False, "Node evaluator package.json is missing."

    return True, None


def ensure_node_evaluator_dependencies() -> None:
    available, reason = node_runtime_available()
    if not available:
        raise RuntimeError(reason or "Node.js runtime is unavailable.")

    node_modules_path, jest_cli_path, _ = _node_runtime_paths()
    if jest_cli_path.exists() and all((node_modules_path / package_name).exists() for package_name in REQUIRED_NODE_PACKAGES):
        return

    completed_process = subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund"],
        cwd=NODE_RUNTIME_DIRECTORY,
        capture_output=True,
        text=True,
        timeout=180,
        env=_node_runtime_environment(),
    )
    if completed_process.returncode != 0:
        error_output = completed_process.stderr.strip() or completed_process.stdout.strip()
        raise RuntimeError(
            "Node evaluator dependencies could not be installed. "
            f"{error_output or 'npm install failed.'}"
        )


def compile_pug_submission(source_code: str) -> Optional[str]:
    ensure_node_evaluator_dependencies()

    with tempfile.TemporaryDirectory() as temporary_directory:
        input_path = Path(temporary_directory) / "index.pug"
        compile_script_path = Path(temporary_directory) / "compile_pug.js"
        input_path.write_text(source_code, encoding="utf-8")
        compile_script_path.write_text(
            """
const fs = require("fs");
const pug = require("pug");

const inputPath = process.argv[2];

try {
  const source = fs.readFileSync(inputPath, "utf8");
  pug.compile(source, { filename: inputPath });
  process.exit(0);
} catch (error) {
  console.error(error && error.message ? error.message : String(error));
  process.exit(1);
}
""".strip(),
            encoding="utf-8",
        )

        completed_process = subprocess.run(
            ["node", str(compile_script_path), str(input_path)],
            capture_output=True,
            text=True,
            timeout=10,
            env=_node_runtime_environment(),
        )

    if completed_process.returncode == 0:
        return None

    return completed_process.stderr.strip() or completed_process.stdout.strip() or "Invalid Pug syntax."


def create_node_workspace(definition: dict, submitted_content: str) -> NodeWorkspace:
    editable_paths = definition["submissionRules"]["editablePaths"]
    if len(editable_paths) != 1:
        raise ValueError(
            "Node Pug evaluator currently supports exactly one editable file."
        )

    editable_path = editable_paths[0]
    temporary_directory = tempfile.TemporaryDirectory()
    root_path = Path(temporary_directory.name)
    editable_file_path = root_path / editable_path
    jest_config_path = root_path / "jest.config.cjs"
    package_json_path = root_path / "package.json"
    jest_setup_path = root_path / "jest.setup.js"

    for file_definition in definition.get("files", []):
        file_path = root_path / file_definition["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_content = file_definition.get("content", "")
        if file_definition["path"] == editable_path:
            file_content = submitted_content

        file_path.write_text(file_content, encoding="utf-8")

    jest_config_path.write_text(
        """
module.exports = {
  rootDir: __dirname,
  testEnvironment: "jsdom",
  testMatch: ["**/*.test.js"],
  setupFiles: ["<rootDir>/jest.setup.js"],
};
""".strip(),
        encoding="utf-8",
    )
    package_json_path.write_text(
        json.dumps(
            {
                "name": "aicodearena-evaluation-workspace",
                "private": True,
            }
        ),
        encoding="utf-8",
    )
    jest_setup_path.write_text(
        """
const util = require("util");

if (typeof global.TextEncoder === "undefined") {
  global.TextEncoder = util.TextEncoder;
}

if (typeof global.TextDecoder === "undefined") {
  global.TextDecoder = util.TextDecoder;
}
""".strip(),
        encoding="utf-8",
    )

    return NodeWorkspace(
        temporary_directory=temporary_directory,
        root_path=root_path,
        editable_file_path=editable_file_path,
        jest_config_path=jest_config_path,
    )


def _normalize_jest_status(
    completed_process: subprocess.CompletedProcess,
    jest_output: dict,
    feedback_text: Optional[str],
) -> Tuple[str, Optional[str], List[Dict[str, Any]], List[str]]:
    if completed_process.returncode == 0 or bool(jest_output.get("success")):
        assertion_results = []
        for suite_result in jest_output.get("testResults", []) or []:
            assertion_results.extend(suite_result.get("assertionResults", []) or [])
        return "passed", feedback_text or None, assertion_results, []

    test_results = jest_output.get("testResults", [])
    if test_results:
        suite_result = test_results[0]
        assertion_results = suite_result.get("assertionResults", []) or []
        failure_messages = []

        for assertion in assertion_results:
            if assertion.get("status") == "failed":
                message = assertion.get("failureMessages", []) or []
                failure_messages.extend(message)

        if suite_result.get("message"):
            failure_messages.append(suite_result.get("message"))

        if failure_messages or suite_result.get("status") == "failed":
            timeout_failure = any(
                "Exceeded timeout" in failure_message or "timed out" in failure_message.lower()
                for failure_message in failure_messages
            )
            if timeout_failure:
                return "timeout", "Test execution timed out.", assertion_results, []
            message = feedback_text or "\n".join(
                text.strip() for text in failure_messages if text.strip()
            )
            return "failed", message or "Jest assertions failed.", assertion_results, []

    stderr_output = (completed_process.stderr or "").strip()
    stdout_output = (completed_process.stdout or "").strip()
    message = feedback_text or stderr_output or stdout_output or "Jest runtime error."
    page_errors = [stderr_output or stdout_output] if (stderr_output or stdout_output) else []
    return "runtime_error", message, [], page_errors


def _run_single_jest_test(
    workspace: NodeWorkspace,
    runtime_definition: dict,
    test_definition: dict,
) -> NodeJestTestResult:
    ensure_node_evaluator_dependencies()

    _, jest_cli_path, _ = _node_runtime_paths()
    test_path = workspace.root_path / test_definition["path"]
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(test_definition["source"], encoding="utf-8")

    output_path = workspace.root_path / ".aicodearena-jest-output.json"
    feedback_path = workspace.root_path / "FEEDBACK"
    if feedback_path.exists():
        feedback_path.unlink()

    timeout_ms = int(test_definition.get("timeoutMs", DEFAULT_NODE_TIMEOUT_MS) or DEFAULT_NODE_TIMEOUT_MS)
    started_at = time.perf_counter()

    try:
        completed_process = subprocess.run(
            [
                "node",
                str(jest_cli_path),
                "--runInBand",
                "--env=jsdom",
                "--config",
                str(workspace.jest_config_path),
                "--runTestsByPath",
                test_definition["path"],
                "--json",
                f"--outputFile={output_path}",
                "--testLocationInResults",
                "--testTimeout",
                str(timeout_ms),
            ],
            cwd=workspace.root_path,
            capture_output=True,
            text=True,
            timeout=max(1, int((timeout_ms / 1000.0) + 2)),
            env=_node_runtime_environment(),
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return NodeJestTestResult(
            test_id=test_definition["id"],
            test_name=test_definition["name"],
            status="timeout",
            points_possible=float(test_definition["points"]),
            points_earned=0.0,
            message="Test execution timed out.",
            diagnostics={"runner": "jest", "test_path": test_definition["path"]},
            duration_ms=duration_ms,
        )
    finally:
        try:
            test_path.unlink()
        except OSError:
            pass

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    feedback_text = None
    if feedback_path.exists():
        feedback_text = feedback_path.read_text(encoding="utf-8").strip() or None
        try:
            feedback_path.unlink()
        except OSError:
            pass

    jest_output = {}
    if output_path.exists():
        try:
            jest_output = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            jest_output = {}
        finally:
            try:
                output_path.unlink()
            except OSError:
                pass

    status, message, assertions, page_errors = _normalize_jest_status(
        completed_process,
        jest_output,
        feedback_text,
    )
    points_possible = float(test_definition["points"])
    points_earned = points_possible if status == "passed" else 0.0

    return NodeJestTestResult(
        test_id=test_definition["id"],
        test_name=test_definition["name"],
        status=status,
        points_possible=points_possible,
        points_earned=points_earned,
        message=message,
        assertions=assertions,
        page_errors=page_errors,
        diagnostics={
            "runner": "jest",
            "test_path": test_definition["path"],
            "feedback_file_present": feedback_text is not None,
            "jest_success": bool(jest_output.get("success")) if jest_output else False,
        },
        duration_ms=duration_ms,
    )


def _build_overall_status(test_results: List[NodeJestTestResult], total_timed_out: bool) -> str:
    if total_timed_out:
        return "Time Limit Exceeded"

    total_points = sum(result.points_possible for result in test_results)
    earned_points = sum(result.points_earned for result in test_results)

    if total_points > 0 and earned_points == total_points:
        return "Accepted"

    if any(result.status in {"runtime_error", "syntax_error", "setup_error"} for result in test_results) and not any(
        result.status in {"passed", "failed", "timeout"} for result in test_results
    ):
        return "Runtime Error"

    return "Wrong Answer"


def _build_stderr(test_results: List[NodeJestTestResult], total_timed_out: bool) -> Optional[str]:
    if total_timed_out:
        return "Total Node evaluation timed out."

    messages = []
    for result in test_results:
        if result.status != "passed" and result.message:
            messages.append(f"{result.test_name}: {result.message}")

    return "\n".join(messages) if messages else None


def evaluate_node_jest_pug_problem(
    definition: dict,
    submitted_content: str,
) -> NodeJestEvaluationResult:
    evaluation_started_at = time.perf_counter()
    runtime_definition = definition.get("runtime", {})
    total_timeout_ms = int(runtime_definition.get("totalTimeoutMs", 30000) or 30000)
    workspace = create_node_workspace(definition, submitted_content)
    test_results: List[NodeJestTestResult] = []
    total_timed_out = False

    try:
        for test_definition in definition.get("tests", []):
            elapsed_ms = int((time.perf_counter() - evaluation_started_at) * 1000)
            if elapsed_ms >= total_timeout_ms:
                total_timed_out = True
                break

            test_results.append(
                _run_single_jest_test(
                    workspace,
                    runtime_definition,
                    test_definition,
                )
            )
    finally:
        workspace.cleanup()

    duration_ms = int((time.perf_counter() - evaluation_started_at) * 1000)
    score_possible = float(sum(float(test["points"]) for test in definition.get("tests", [])))
    score_earned = float(sum(result.points_earned for result in test_results))
    score_percentage = (score_earned / score_possible * 100.0) if score_possible else 0.0
    status = _build_overall_status(test_results, total_timed_out)
    stdout = "PASS" if status == "Accepted" else f"Score: {score_earned:g}/{score_possible:g}"
    stderr = _build_stderr(test_results, total_timed_out)

    return NodeJestEvaluationResult(
        status=status,
        score_earned=score_earned,
        score_possible=score_possible,
        score_percentage=score_percentage,
        test_results=test_results,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
    )
