import os
import subprocess
import unittest
from unittest.mock import patch

from app.judge0_client import run_python_code


class Judge0ClientTests(unittest.TestCase):
    def test_mock_mode_returns_accepted_and_stdout(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            result = run_python_code("print('PASS')")

        self.assertEqual(result["status"], "Accepted")
        self.assertEqual(result["stdout"], "PASS\n")
        self.assertEqual(result["stderr"], "")
        self.assertIsNone(result["compile_output"])
        self.assertIsNone(result["memory"])

    def test_mock_mode_returns_runtime_error_and_stderr(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            result = run_python_code("raise ValueError('example failure')")

        self.assertEqual(result["status"], "Runtime Error")
        self.assertIn("ValueError: example failure", result["stderr"])

    @patch("app.judge0_client.subprocess.run")
    def test_mock_mode_returns_time_limit_exceeded(self, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(
            cmd=["python", "-c", "while True: pass"],
            timeout=5,
            output="started\n",
            stderr="",
        )

        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            result = run_python_code("while True: pass")

        self.assertEqual(result["status"], "Time Limit Exceeded")
        self.assertEqual(result["stdout"], "started\n")
        self.assertIn("timed out", result["stderr"])

    def test_missing_url_returns_configuration_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = run_python_code("print('hello')")

        self.assertEqual(result["status"], "configuration_error")
        self.assertIn("JUDGE0_URL", result["stderr"])
        self.assertIsNone(result["stdout"])

    @patch("app.judge0_client.time.sleep")
    @patch("app.judge0_client._send_json_request")
    def test_returns_completed_judge0_result(
        self,
        send_request,
        sleep,
    ) -> None:
        send_request.side_effect = [
            {"token": "sample-token"},
            {"status": {"id": 2, "description": "Processing"}},
            {
                "status": {"id": 3, "description": "Accepted"},
                "stdout": "PASS\n",
                "stderr": None,
                "compile_output": None,
                "time": "0.01",
                "memory": 1024,
            },
        ]

        with patch.dict(os.environ, {"JUDGE0_URL": "https://judge.example"}, clear=True):
            result = run_python_code("print('PASS')")

        self.assertEqual(result["status"], "Accepted")
        self.assertEqual(result["stdout"], "PASS\n")
        self.assertEqual(result["time"], "0.01")
        self.assertEqual(result["memory"], 1024)
        sleep.assert_called_once_with(0.5)


if __name__ == "__main__":
    unittest.main()
