import os
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import ModelRunRequest, list_models, run_model_solution
from app.model_adapters import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    GEMINI_MINIMUM_TIMEOUT_SECONDS,
    GENERIC_OPENROUTER_DESCRIPTION,
    OPENROUTER_MODEL_PREFIX,
    build_openrouter_unavailable_payload,
    build_openrouter_model_catalog,
    generate_solution,
    get_default_competition_models,
    get_gemini_timeout_milliseconds,
    get_active_model_catalog,
    parse_openrouter_models,
    prettify_openrouter_model_name,
    get_provider_timeout_seconds,
    get_provider_request_timeout_seconds,
    get_competition_stale_threshold_seconds,
)
from app.models import EvaluationResult, Problem
from tests.provider_fixtures import (
    REAL_GEMINI,
    REAL_GROQ,
    REAL_MISTRAL,
    TWO_SUM_ACCEPTED_AND_FAILED,
    TWO_SUM_FORMAT_BAD,
    build_generate_solution_side_effect,
)


class ModelAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        TestSession = sessionmaker(bind=self.engine)
        self.database = TestSession()
        self.problem = Problem(
            title="Two Sum",
            category="Arrays",
            difficulty="Easy",
            language="Python",
            description="Return two indices whose values add up to the target.",
            starter_code="def two_sum(numbers, target):\n    pass\n",
            required_file="solution.py",
            required_function="two_sum",
        )
        self.database.add(self.problem)
        self.database.commit()
        self.database.refresh(self.problem)

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def _run_provider(self) -> dict:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(
                    {REAL_GEMINI: TWO_SUM_ACCEPTED_AND_FAILED[REAL_GEMINI]}
                ),
            ):
                return run_model_solution(
                    self.problem.id,
                    ModelRunRequest(model_name=REAL_GEMINI),
                    self.database,
                )

    def test_real_provider_run_returns_accepted(self) -> None:
        response = self._run_provider()

        self.assertEqual(response["execution_result"]["status"], "Accepted")
        self.assertEqual(response["execution_result"]["stdout"], "PASS\n")
        self.assertNotIn("```", response["raw_response"])
        self.assertEqual(response["raw_response"].strip(), response["cleaned_code"])

    def test_real_provider_run_saves_model_name(self) -> None:
        response = self._run_provider()
        saved_result = self.database.get(EvaluationResult, response["result_id"])

        self.assertIsNotNone(saved_result)
        self.assertEqual(saved_result.model_name, REAL_GEMINI)
        self.assertEqual(saved_result.mode, "mock")

    def test_format_bad_model_returns_format_error(self) -> None:
        with patch.dict(os.environ, {"JUDGE0_MODE": "mock"}, clear=True):
            with patch(
                "app.main.generate_solution",
                side_effect=build_generate_solution_side_effect(TWO_SUM_FORMAT_BAD),
            ):
                response = run_model_solution(
                    self.problem.id,
                    ModelRunRequest(model_name=REAL_GEMINI),
                    self.database,
                )

        self.assertEqual(response["execution_result"]["status"], "FORMAT_ERROR")
        self.assertIsNone(response["cleaned_code"])
        self.assertIn("Expected raw executable code only", response["execution_result"]["stderr"])
        self.assertIn("```python", response["raw_response"])

    def test_unsupported_model_returns_clear_error(self) -> None:
        request = ModelRunRequest(model_name="unknown_model")

        with self.assertRaises(HTTPException) as raised:
            run_model_solution(self.problem.id, request, self.database)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Unsupported model_name", raised.exception.detail)

    def test_active_model_catalog_contains_no_mock_models(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            catalog = get_active_model_catalog()

        self.assertEqual(
            [model["id"] for model in catalog],
            [REAL_GEMINI, REAL_GROQ, REAL_MISTRAL],
        )
        self.assertTrue(all("mock" not in model["id"] for model in catalog))
        self.assertEqual(catalog[0]["model_creator"], "Google DeepMind")
        self.assertEqual(catalog[1]["api_provider"], "Groq")
        self.assertEqual(catalog[2]["provider_type"], "direct_provider")
        self.assertIn("low-latency responses", catalog[0]["description"])
        self.assertIn("70-billion-parameter", catalog[1]["description"])
        self.assertIn("compact instruction-tuned", catalog[2]["description"])

    def test_models_endpoint_contains_no_mock_models(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            response = list_models()

        self.assertEqual(
            [model["id"] for model in response],
            [REAL_GEMINI, REAL_GROQ, REAL_MISTRAL],
        )
        self.assertTrue(all("mock" not in model["id"] for model in response))
        self.assertEqual(
            response[0]["description"].startswith("Google's lightweight Gemini model"),
            True,
        )
        self.assertEqual(response[1]["model_creator"], "Meta")
        self.assertEqual(response[2]["api_provider"], "Mistral AI")

    def test_parse_openrouter_models_trims_whitespace_and_ignores_empty_entries(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_MODELS": " qwen/qwen3-coder:free, , deepseek/deepseek-r1:free ,, ",
            },
            clear=True,
        ):
            self.assertEqual(
                parse_openrouter_models(),
                ["qwen/qwen3-coder:free", "deepseek/deepseek-r1:free"],
            )

    def test_openrouter_catalog_registers_multiple_free_models(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_MODELS": (
                    "qwen/qwen3-coder:free,"
                    "deepseek/deepseek-r1:free,"
                    "google/gemma-3-27b-it:free"
                ),
            },
            clear=True,
        ):
            catalog = build_openrouter_model_catalog()

        self.assertEqual(
            [model["id"] for model in catalog],
            [
                "openrouter:qwen/qwen3-coder:free",
                "openrouter:deepseek/deepseek-r1:free",
                "openrouter:google/gemma-3-27b-it:free",
            ],
        )
        self.assertEqual(catalog[0]["display_name"], "Qwen 3 Coder")
        self.assertEqual(catalog[1]["display_name"], "DeepSeek R1")
        self.assertEqual(catalog[2]["display_name"], "Gemma 3 27B IT")
        self.assertTrue(all(model["provider"] == "openrouter" for model in catalog))
        self.assertTrue(all(model["provider_type"] == "model_router" for model in catalog))

    def test_openrouter_catalog_uses_curated_exact_descriptions_when_available(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_MODELS": (
                    "openai/gpt-oss-20b:free,"
                    "cohere/north-mini-code:free,"
                    "poolside/laguna-s-2.1:free,"
                    "google/gemma-4-31b-it:free,"
                    "inclusionai/ling-3.0-flash:free"
                ),
            },
            clear=True,
        ):
            catalog = build_openrouter_model_catalog()

        descriptions = {model["id"]: model["description"] for model in catalog}
        self.assertIn("open-weight GPT-OSS 20B", descriptions["openrouter:openai/gpt-oss-20b:free"])
        self.assertIn("specialized coding model", descriptions["openrouter:cohere/north-mini-code:free"])
        self.assertIn("coding-focused model", descriptions["openrouter:poolside/laguna-s-2.1:free"])
        self.assertIn("Gemma 4 31B", descriptions["openrouter:google/gemma-4-31b-it:free"])
        self.assertIn("Mixture-of-Experts", descriptions["openrouter:inclusionai/ling-3.0-flash:free"])

    def test_openrouter_catalog_uses_fallback_description_for_unknown_model(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_MODELS": "example/unknown-coder:free"},
            clear=True,
        ):
            catalog = build_openrouter_model_catalog()

        self.assertEqual(catalog[0]["description"], GENERIC_OPENROUTER_DESCRIPTION)

    def test_openrouter_non_free_models_are_skipped_with_warning(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free,anthropic/claude-sonnet-4",
            },
            clear=True,
        ):
            with self.assertLogs("app.model_adapters", level="WARNING") as captured_logs:
                catalog = build_openrouter_model_catalog()

        self.assertEqual(
            [model["id"] for model in catalog],
            ["openrouter:qwen/qwen3-coder:free"],
        )
        self.assertIn("only :free models are allowed", "\n".join(captured_logs.output))

    def test_active_model_catalog_includes_openrouter_models(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_MODELS": "qwen/qwen3-coder:free"},
            clear=True,
        ):
            catalog = get_active_model_catalog()

        self.assertEqual(
            [model["id"] for model in catalog],
            [
                REAL_GEMINI,
                REAL_GROQ,
                REAL_MISTRAL,
                "openrouter:qwen/qwen3-coder:free",
            ],
        )

    def test_default_competition_models_include_openrouter_models(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_MODELS": "qwen/qwen3-coder:free"},
            clear=True,
        ):
            model_ids = get_default_competition_models()

        self.assertEqual(
            model_ids,
            [
                REAL_GEMINI,
                REAL_GROQ,
                REAL_MISTRAL,
                "openrouter:qwen/qwen3-coder:free",
            ],
        )

    def test_openrouter_name_falls_back_to_raw_model_id_when_unprettifiable(self) -> None:
        self.assertEqual(prettify_openrouter_model_name("/"), "/")

    def test_gemini_missing_api_key_returns_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as raised:
                generate_solution("Title: Two Sum", "gemini-flash-latest")

        self.assertIn("GEMINI_API_KEY", str(raised.exception))

    def test_groq_missing_api_key_returns_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as raised:
                generate_solution("Title: Two Sum", "groq:llama-3.3-70b-versatile")

        self.assertIn("GROQ_API_KEY", str(raised.exception))

    def test_mistral_missing_api_key_returns_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as raised:
                generate_solution("Title: Two Sum", REAL_MISTRAL)

        self.assertIn("MISTRAL_API_KEY", str(raised.exception))

    def test_openrouter_missing_api_key_returns_clear_error(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_MODELS": "qwen/qwen3-coder:free"},
            clear=True,
        ):
            with self.assertRaises(ValueError) as raised:
                generate_solution(
                    "Title: Two Sum",
                    "openrouter:qwen/qwen3-coder:free",
                )

        self.assertIn("OPENROUTER_API_KEY", str(raised.exception))

    def test_groq_request_failure_returns_clear_error(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.side_effect = RuntimeError("request failed")

        with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
            with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=True):
                with self.assertRaises(ValueError) as raised:
                    generate_solution("Title: Two Sum", "groq:llama-3.3-70b-versatile")

        self.assertIn("Groq request failed", str(raised.exception))

    def test_dispatcher_selects_gemini_provider(self) -> None:
        fake_response = Mock()
        fake_response.text = "def solution():\n    return 1"
        fake_client = Mock()
        fake_client.models.generate_content.return_value = fake_response
        fake_genai = Mock()
        fake_genai.types.HttpOptions.side_effect = lambda **kwargs: kwargs
        fake_genai.Client.return_value = fake_client

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            with patch("app.model_adapters.importlib.import_module", return_value=fake_genai):
                response = generate_solution("Title: Two Sum", "gemini-flash-latest")

        self.assertEqual(response["model_name"], "gemini-flash-latest")
        self.assertEqual(response["raw_response"], "def solution():\n    return 1")
        fake_genai.Client.assert_called_once_with(
            api_key="test-key",
            http_options={"timeout": DEFAULT_PROVIDER_TIMEOUT_SECONDS * 1000},
        )
        fake_client.models.generate_content.assert_called_once()

    def test_dispatcher_selects_groq_provider(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": "def solution():\n    return 2"
                            }
                        }
                    ]
                }
            ),
        )

        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=True):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                response = generate_solution(
                    "Title: Two Sum",
                    "groq:llama-3.3-70b-versatile",
                )

        self.assertEqual(response["model_name"], "groq:llama-3.3-70b-versatile")
        self.assertEqual(response["raw_response"], "def solution():\n    return 2")
        requests_module.post.assert_called_once()
        self.assertEqual(
            requests_module.post.call_args.kwargs["timeout"],
            DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        )

    def test_dispatcher_selects_mistral_provider(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": "def solution():\n    return 3"
                            }
                        }
                    ]
                }
            ),
        )

        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}, clear=True):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                response = generate_solution(
                    "Title: Two Sum",
                    REAL_MISTRAL,
                )

        self.assertEqual(response["model_name"], REAL_MISTRAL)
        self.assertEqual(response["raw_response"], "def solution():\n    return 3")
        requests_module.post.assert_called_once()
        self.assertEqual(
            requests_module.post.call_args.kwargs["timeout"],
            DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        )

    def test_dispatcher_selects_openrouter_provider(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": "def solution():\n    return 4"
                            }
                        }
                    ]
                }
            ),
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                response = generate_solution(
                    "Title: Two Sum",
                    "openrouter:qwen/qwen3-coder:free",
                )

        self.assertEqual(response["model_name"], "openrouter:qwen/qwen3-coder:free")
        self.assertEqual(response["raw_response"], "def solution():\n    return 4")
        requests_module.post.assert_called_once()
        self.assertEqual(
            requests_module.post.call_args.kwargs["json"]["model"],
            "qwen/qwen3-coder:free",
        )
        self.assertEqual(
            requests_module.post.call_args.kwargs["json"]["temperature"],
            0,
        )
        self.assertEqual(
            requests_module.post.call_args.kwargs["timeout"],
            DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        )

    def test_mistral_request_failure_returns_clear_error(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.side_effect = RuntimeError("request failed")

        with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
            with patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}, clear=True):
                with self.assertRaises(ValueError) as raised:
                    generate_solution("Title: Two Sum", REAL_MISTRAL)

        self.assertIn("Mistral request failed", str(raised.exception))

    def test_openrouter_request_failure_returns_clear_error(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.side_effect = RuntimeError("request failed")

        with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
            with patch.dict(
                os.environ,
                {
                    "OPENROUTER_API_KEY": "test-key",
                    "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
                },
                clear=True,
            ):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:qwen/qwen3-coder:free",
                    )

        self.assertIn("OpenRouter request failed", str(raised.exception))

    def test_mistral_empty_response_returns_clear_error(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"choices": [{"message": {"content": ""}}]}),
        )

        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}, clear=True):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution("Title: Two Sum", REAL_MISTRAL)

        self.assertIn("Mistral returned an empty response", str(raised.exception))

    def test_mistral_malformed_response_returns_clear_error(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"choices": [{}]}),
        )

        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"}, clear=True):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution("Title: Two Sum", REAL_MISTRAL)

        self.assertIn("Mistral returned an empty response", str(raised.exception))

    def test_openrouter_empty_response_returns_clear_error(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"choices": [{"message": {"content": ""}}]}),
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:qwen/qwen3-coder:free",
                    )

        self.assertIn("OpenRouter returned an empty response", str(raised.exception))

    def test_openrouter_malformed_response_returns_clear_error(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"choices": [{}]}),
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:qwen/qwen3-coder:free",
                    )

        self.assertIn("OpenRouter returned an empty response", str(raised.exception))

    def test_openrouter_authentication_failure_returns_status_error(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=401,
            text='{"error":"Unauthorized"}',
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:qwen/qwen3-coder:free",
                    )

        self.assertIn("status 401", str(raised.exception))
        self.assertNotIn("test-key", str(raised.exception))

    def test_openrouter_quota_failure_returns_status_error(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=429,
            text='{"error":"Quota exceeded"}',
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:qwen/qwen3-coder:free",
                    )

        self.assertIn("status 429", str(raised.exception))
        self.assertNotIn("test-key", str(raised.exception))

    def test_openrouter_unavailable_404_with_suggested_paid_slug_is_normalized(self) -> None:
        response_text = (
            '{"error":{"message":"This model is unavailable for free. '
            'The paid version is available now — use this slug instead: '
            'google/gemma-3-27b-it"}}'
        )
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=404,
            text=response_text,
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "google/gemma-3-27b-it:free",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:google/gemma-3-27b-it:free",
                    )

        message = str(raised.exception)
        self.assertIn("Adapter Error", message)
        self.assertIn("Model unavailable", message)
        self.assertIn("Configured: google/gemma-3-27b-it:free", message)
        self.assertIn(
            "Suggested replacement: google/gemma-3-27b-it (paid)",
            message,
        )
        self.assertIn("Provider: OpenRouter", message)
        self.assertIn("HTTP status: 404", message)
        self.assertNotIn(response_text, message)
        self.assertNotIn("test-key", message)
        self.assertEqual(requests_module.post.call_count, 1)
        self.assertEqual(
            requests_module.post.call_args.kwargs["json"]["model"],
            "google/gemma-3-27b-it:free",
        )

    def test_openrouter_unavailable_404_without_suggested_slug_is_normalized(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=404,
            text='{"error":{"message":"Model not found on the free tier."}}',
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:qwen/qwen3-coder:free",
                    )

        message = str(raised.exception)
        self.assertIn("Model unavailable", message)
        self.assertNotIn("Suggested replacement:", message)

    def test_openrouter_non_json_404_response_is_normalized(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=404,
            text="No endpoints found for your model selection.",
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:qwen/qwen3-coder:free",
                    )

        self.assertIn("Model unavailable", str(raised.exception))

    def test_openrouter_malformed_json_404_response_is_normalized(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=404,
            text='{"error":{"message":"This model is unavailable for free."}',
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:qwen/qwen3-coder:free",
                    )

        self.assertIn("Model unavailable", str(raised.exception))

    def test_openrouter_unavailable_payload_contains_expected_fields(self) -> None:
        payload = build_openrouter_unavailable_payload(
            configured_model="google/gemma-3-27b-it:free",
            status_code=404,
            response_text=(
                '{"error":{"message":"This model is unavailable for free. '
                'The paid version is available now — use this slug instead: '
                'google/gemma-3-27b-it"}}'
            ),
        )

        self.assertEqual(
            payload,
            {
                "status": "Model Unavailable",
                "short_message": (
                    "The configured OpenRouter model is no longer available on the free tier."
                ),
                "configured_model": "google/gemma-3-27b-it:free",
                "suggested_model": "google/gemma-3-27b-it",
                "provider": "OpenRouter",
                "http_status": 404,
            },
        )

    def test_gemini_timeout_returns_clear_error(self) -> None:
        fake_client = Mock()
        fake_client.models.generate_content.side_effect = RuntimeError(
            "operation timed out"
        )
        fake_genai = Mock()
        fake_genai.types.HttpOptions.side_effect = lambda **kwargs: kwargs
        fake_genai.Client.return_value = fake_client

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            with patch("app.model_adapters.importlib.import_module", return_value=fake_genai):
                with self.assertRaises(ValueError) as raised:
                    generate_solution("Title: Two Sum", REAL_GEMINI)

        self.assertIn("timed out", str(raised.exception).lower())

    def test_openrouter_timeout_returns_clear_error(self) -> None:
        requests_module = Mock()
        timeout_error = type("Timeout", (RuntimeError,), {})
        requests_module.RequestException = RuntimeError
        requests_module.post.side_effect = timeout_error("operation timed out")

        with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
            with patch.dict(
                os.environ,
                {
                    "OPENROUTER_API_KEY": "test-key",
                    "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
                },
                clear=True,
            ):
                with self.assertRaises(ValueError) as raised:
                    generate_solution(
                        "Title: Two Sum",
                        "openrouter:qwen/qwen3-coder:free",
                    )

        self.assertIn("timed out", str(raised.exception).lower())

    def test_unsupported_openrouter_model_not_registered_when_invalid(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_MODELS": "qwen/qwen3-coder"},
            clear=True,
        ):
            with self.assertRaises(ValueError) as raised:
                generate_solution(
                    "Title: Two Sum",
                    f"{OPENROUTER_MODEL_PREFIX}qwen/qwen3-coder",
                )

        self.assertIn("Unsupported model_name", str(raised.exception))

    def test_missing_real_provider_configuration_does_not_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as raised:
                generate_solution("Title: Two Sum", REAL_GEMINI)

        self.assertIn("GEMINI_API_KEY", str(raised.exception))

    def test_provider_timeout_defaults_to_120_seconds(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                get_provider_timeout_seconds(),
                DEFAULT_PROVIDER_TIMEOUT_SECONDS,
            )

    def test_provider_timeout_reads_environment_value_in_seconds(self) -> None:
        with patch.dict(
            os.environ,
            {"MODEL_EXECUTION_TIMEOUT_SECONDS": "45"},
            clear=True,
        ):
            self.assertEqual(get_provider_timeout_seconds(), 45)

    def test_provider_timeout_uses_legacy_env_when_primary_missing(self) -> None:
        with patch.dict(
            os.environ,
            {"AICODEARENA_PROVIDER_TIMEOUT_SECONDS": "33"},
            clear=True,
        ):
            self.assertEqual(get_provider_timeout_seconds(), 33)

    def test_fractional_provider_timeout_is_preserved(self) -> None:
        with patch.dict(
            os.environ,
            {"MODEL_EXECUTION_TIMEOUT_SECONDS": "5.5"},
            clear=True,
        ):
            self.assertEqual(get_provider_timeout_seconds(), 5.5)
            self.assertEqual(get_provider_request_timeout_seconds(), 5.5)

    def test_invalid_provider_timeout_falls_back_to_default(self) -> None:
        with patch.dict(
            os.environ,
            {"MODEL_EXECUTION_TIMEOUT_SECONDS": "not-a-number"},
            clear=True,
        ):
            self.assertEqual(
                get_provider_timeout_seconds(),
                DEFAULT_PROVIDER_TIMEOUT_SECONDS,
            )

    def test_non_positive_provider_timeout_falls_back_to_default(self) -> None:
        for value in ("0", "-5"):
            with self.subTest(value=value):
                with patch.dict(
                    os.environ,
                    {"MODEL_EXECUTION_TIMEOUT_SECONDS": value},
                    clear=True,
                ):
                    self.assertEqual(
                        get_provider_timeout_seconds(),
                        DEFAULT_PROVIDER_TIMEOUT_SECONDS,
                    )

    def test_stale_threshold_adds_grace_period(self) -> None:
        with patch.dict(
            os.environ,
            {"MODEL_EXECUTION_TIMEOUT_SECONDS": "120"},
            clear=True,
        ):
            self.assertEqual(get_competition_stale_threshold_seconds(), 150.0)

    def test_gemini_timeout_conversion_uses_milliseconds(self) -> None:
        self.assertEqual(get_gemini_timeout_milliseconds(120), 120000)

    def test_gemini_timeout_conversion_never_sends_one_second_deadline(self) -> None:
        self.assertEqual(
            get_gemini_timeout_milliseconds(120) / 1000,
            120,
        )

    def test_gemini_timeout_respects_sdk_minimum(self) -> None:
        self.assertEqual(
            get_gemini_timeout_milliseconds(1),
            GEMINI_MINIMUM_TIMEOUT_SECONDS * 1000,
        )

    def test_dispatcher_selects_gemini_provider_with_env_timeout(self) -> None:
        fake_response = Mock()
        fake_response.text = "def solution():\n    return 1"
        fake_client = Mock()
        fake_client.models.generate_content.return_value = fake_response
        fake_genai = Mock()
        fake_genai.types.HttpOptions.side_effect = lambda **kwargs: kwargs
        fake_genai.Client.return_value = fake_client

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-key",
                "MODEL_EXECUTION_TIMEOUT_SECONDS": "120",
            },
            clear=True,
        ):
            with patch(
                "app.model_adapters.importlib.import_module",
                return_value=fake_genai,
            ):
                generate_solution("Title: Two Sum", "gemini-flash-latest")

        self.assertEqual(
            fake_genai.Client.call_args.kwargs["http_options"]["timeout"],
            120000,
        )

    def test_groq_timeout_uses_authoritative_execution_timeout(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "choices": [
                        {"message": {"content": "def solution():\n    return 2"}}
                    ]
                }
            ),
        )

        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "test-key",
                "MODEL_EXECUTION_TIMEOUT_SECONDS": "5.5",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                generate_solution("Title: Two Sum", REAL_GROQ)

        self.assertEqual(requests_module.post.call_args.kwargs["timeout"], 5.5)

    def test_mistral_timeout_uses_authoritative_execution_timeout(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "choices": [
                        {"message": {"content": "def solution():\n    return 3"}}
                    ]
                }
            ),
        )

        with patch.dict(
            os.environ,
            {
                "MISTRAL_API_KEY": "test-key",
                "MODEL_EXECUTION_TIMEOUT_SECONDS": "5.5",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                generate_solution("Title: Two Sum", REAL_MISTRAL)

        self.assertEqual(requests_module.post.call_args.kwargs["timeout"], 5.5)

    def test_openrouter_timeout_uses_authoritative_execution_timeout(self) -> None:
        requests_module = Mock()
        requests_module.RequestException = RuntimeError
        requests_module.post.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "choices": [
                        {"message": {"content": "def solution():\n    return 4"}}
                    ]
                }
            ),
        )

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_MODELS": "qwen/qwen3-coder:free",
                "MODEL_EXECUTION_TIMEOUT_SECONDS": "5.5",
            },
            clear=True,
        ):
            with patch("app.model_adapters.importlib.import_module", return_value=requests_module):
                generate_solution("Title: Two Sum", "openrouter:qwen/qwen3-coder:free")

        self.assertEqual(requests_module.post.call_args.kwargs["timeout"], 5.5)


if __name__ == "__main__":
    unittest.main()
