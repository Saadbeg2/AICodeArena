import json
import os
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PYTHON_LANGUAGE_ID = 71
POLL_ATTEMPTS = 20
POLL_INTERVAL_SECONDS = 0.5
MOCK_TIMEOUT_SECONDS = 5


def _error_result(status: str, message: str) -> dict[str, Any]:
    return {
        "status": status,
        "stdout": None,
        "stderr": message,
        "compile_output": None,
        "time": None,
        "memory": None,
    }


def _request_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("JUDGE0_API_KEY")
    api_host = os.getenv("JUDGE0_API_HOST")

    if api_key and api_host:
        headers["X-RapidAPI-Key"] = api_key
        headers["X-RapidAPI-Host"] = api_host
    elif api_key:
        headers["X-Auth-Token"] = api_key

    return headers


def _send_json_request(request: Request) -> dict[str, Any]:
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _format_result(result: dict[str, Any]) -> dict[str, Any]:
    status = result.get("status", {})
    status_description = (
        status.get("description", "Unknown")
        if isinstance(status, dict)
        else str(status)
    )

    return {
        "status": status_description,
        "stdout": result.get("stdout"),
        "stderr": result.get("stderr"),
        "compile_output": result.get("compile_output"),
        "time": result.get("time"),
        "memory": result.get("memory"),
    }


def _timeout_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _run_python_code_locally(source_code: str) -> dict[str, Any]:
    """Run fixed development code locally. This is not a security sandbox."""
    started_at = time.perf_counter()

    try:
        completed = subprocess.run(
            [sys.executable, "-c", source_code],
            capture_output=True,
            text=True,
            timeout=MOCK_TIMEOUT_SECONDS,
            check=False,
        )
        elapsed = time.perf_counter() - started_at

        return {
            "status": "Accepted" if completed.returncode == 0 else "Runtime Error",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "compile_output": None,
            "time": f"{elapsed:.3f}",
            "memory": None,
        }
    except subprocess.TimeoutExpired as error:
        elapsed = time.perf_counter() - started_at
        stdout = _timeout_output(error.stdout)
        captured_stderr = _timeout_output(error.stderr).strip()
        timeout_message = (
            f"Execution timed out after {MOCK_TIMEOUT_SECONDS} seconds."
        )
        stderr = (
            f"{captured_stderr}\n{timeout_message}"
            if captured_stderr
            else timeout_message
        )

        return {
            "status": "Time Limit Exceeded",
            "stdout": stdout,
            "stderr": stderr,
            "compile_output": None,
            "time": f"{elapsed:.3f}",
            "memory": None,
        }


def run_python_code(source_code: str) -> dict[str, Any]:
    """Run Python locally in mock mode or submit it to Judge0."""
    if os.getenv("JUDGE0_MODE", "").strip().lower() == "mock":
        return _run_python_code_locally(source_code)

    judge0_url = os.getenv("JUDGE0_URL")

    if not judge0_url:
        return _error_result(
            "configuration_error",
            "Judge0 is not configured. Set the JUDGE0_URL environment variable.",
        )

    submissions_url = f"{judge0_url.rstrip('/')}/submissions"
    payload = json.dumps(
        {
            "source_code": source_code,
            "language_id": PYTHON_LANGUAGE_ID,
        }
    ).encode("utf-8")

    submit_request = Request(
        f"{submissions_url}?base64_encoded=false&wait=false",
        data=payload,
        headers=_request_headers(),
        method="POST",
    )

    try:
        submission = _send_json_request(submit_request)
        token = submission.get("token")

        if not token:
            message = submission.get("error", "Judge0 did not return a submission token.")
            return _error_result("submission_error", str(message))

        result_url = (
            f"{submissions_url}/{token}"
            "?base64_encoded=false&fields=stdout,stderr,compile_output,time,memory,status"
        )

        for _ in range(POLL_ATTEMPTS):
            result_request = Request(result_url, headers=_request_headers(), method="GET")
            result = _send_json_request(result_request)
            status = result.get("status", {})
            status_id = status.get("id") if isinstance(status, dict) else None

            if status_id not in (1, 2):
                return _format_result(result)

            time.sleep(POLL_INTERVAL_SECONDS)

        return _error_result(
            "timeout",
            "Judge0 did not finish the submission within 10 seconds.",
        )
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        return _error_result(
            "http_error",
            f"Judge0 returned HTTP {error.code}: {response_body}",
        )
    except (URLError, TimeoutError) as error:
        return _error_result("connection_error", f"Could not reach Judge0: {error}")
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        return _error_result("response_error", f"Invalid Judge0 response: {error}")
