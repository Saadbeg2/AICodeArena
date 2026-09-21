import importlib
import json
import logging
import os
import math
import re
from typing import Callable, Dict, List


ProviderFunction = Callable[[str, str], Dict[str, str]]
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 120
GEMINI_MINIMUM_TIMEOUT_SECONDS = 10
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL_PREFIX = "openrouter:"

logger = logging.getLogger(__name__)

GENERIC_OPENROUTER_DESCRIPTION = (
    "Free OpenRouter model routed through the OpenRouter chat completions API."
)
MODEL_DESCRIPTION_OVERRIDES = {
    "gemini-flash-latest": (
        "Google's lightweight Gemini model optimized for fast code generation, "
        "reasoning, and low-latency responses. Designed for rapid iteration "
        "while maintaining strong programming performance."
    ),
    "groq:llama-3.3-70b-versatile": (
        "Meta's 70-billion-parameter Llama 3.3 model served through Groq's "
        "low-latency inference platform. Designed for strong instruction "
        "following, reasoning, and code generation."
    ),
    "mistral:mistral-small-latest": (
        "Mistral AI's compact instruction-tuned model focused on efficient "
        "reasoning, code generation, and software development tasks with "
        "relatively low latency."
    ),
    "openrouter:openai/gpt-oss-20b:free": (
        "OpenAI's open-weight GPT-OSS 20B model designed for coding, "
        "reasoning, and general instruction following. Accessed through "
        "OpenRouter's free model routing infrastructure."
    ),
    "openrouter:cohere/north-mini-code:free": (
        "Cohere's specialized coding model built for code generation, "
        "software engineering, agentic development workflows, and "
        "repository-level programming tasks."
    ),
    "openrouter:poolside/laguna-s-2.1:free": (
        "Poolside's coding-focused model designed for software engineering, "
        "complex code generation, repository understanding, and agentic "
        "development tasks."
    ),
    "openrouter:google/gemma-4-31b-it:free": (
        "Google's instruction-tuned Gemma 4 31B model offering strong "
        "reasoning, multilingual support, long-context understanding, "
        "and competitive programming capability."
    ),
    "openrouter:inclusionai/ling-3.0-flash:free": (
        "Inclusion AI's Mixture-of-Experts model focused on fast inference, "
        "efficient token usage, general reasoning, and strong programming "
        "performance."
    ),
}


def get_model_description(model_id: str, fallback_description: str) -> str:
    return MODEL_DESCRIPTION_OVERRIDES.get(model_id, fallback_description)

BASE_MODEL_CATALOG: List[dict] = [
    {
        "id": "gemini-flash-latest",
        "display_name": "Gemini Flash Latest",
        "provider": "gemini",
        "model_creator": "Google DeepMind",
        "api_provider": "Google AI Studio",
        "description": get_model_description(
            "gemini-flash-latest",
            "Fast Gemini model for general code generation and evaluation demos.",
        ),
        "provider_type": "direct_provider",
    },
    {
        "id": "groq:llama-3.3-70b-versatile",
        "display_name": "Groq Llama 3.3 70B Versatile",
        "provider": "groq",
        "model_creator": "Meta",
        "api_provider": "Groq",
        "description": get_model_description(
            "groq:llama-3.3-70b-versatile",
            "Meta Llama 3.3 70B served through Groq's low-latency inference API.",
        ),
        "provider_type": "direct_provider",
    },
    {
        "id": "mistral:mistral-small-latest",
        "display_name": "Mistral Small Latest",
        "provider": "mistral",
        "model_creator": "Mistral AI",
        "api_provider": "Mistral AI",
        "description": get_model_description(
            "mistral:mistral-small-latest",
            "Compact Mistral model exposed through the official Mistral chat completions API.",
        ),
        "provider_type": "direct_provider",
    },
]

GEMINI_MODELS = {"gemini-flash-latest"}
GROQ_MODELS = {
    "groq:llama-3.3-70b-versatile": "llama-3.3-70b-versatile",
}
MISTRAL_MODELS = {
    "mistral:mistral-small-latest": "mistral-small-latest",
}


def get_provider_timeout_seconds() -> float:
    raw_value = os.getenv(
        "MODEL_EXECUTION_TIMEOUT_SECONDS",
        os.getenv(
            "AICODEARENA_PROVIDER_TIMEOUT_SECONDS",
            str(DEFAULT_PROVIDER_TIMEOUT_SECONDS),
        ),
    ).strip()

    try:
        timeout_value = float(raw_value)
    except ValueError:
        return float(DEFAULT_PROVIDER_TIMEOUT_SECONDS)

    if not math.isfinite(timeout_value) or timeout_value <= 0:
        return float(DEFAULT_PROVIDER_TIMEOUT_SECONDS)

    return timeout_value


def get_provider_request_timeout_seconds() -> float:
    return get_provider_timeout_seconds()


def get_competition_stale_grace_seconds() -> float:
    return 30.0


def get_competition_stale_threshold_seconds() -> float:
    return get_provider_timeout_seconds() + get_competition_stale_grace_seconds()


def get_gemini_timeout_milliseconds(
    provider_timeout_seconds: float,
) -> int:
    gemini_timeout_seconds = max(
        provider_timeout_seconds,
        float(GEMINI_MINIMUM_TIMEOUT_SECONDS),
    )
    return int(math.ceil(gemini_timeout_seconds * 1000))


def _is_timeout_error(error: Exception) -> bool:
    error_name = type(error).__name__.lower()
    error_message = str(error).lower()
    return (
        "timeout" in error_name
        or "deadline" in error_name
        or "timed out" in error_message
        or "deadline exceeded" in error_message
    )


def get_active_model_catalog() -> List[dict]:
    active_models = [dict(model_definition) for model_definition in BASE_MODEL_CATALOG]
    active_models.extend(build_openrouter_model_catalog())
    return active_models


def get_default_competition_models() -> List[str]:
    return [model_definition["id"] for model_definition in get_active_model_catalog()]


def parse_openrouter_models() -> List[str]:
    raw_value = os.getenv("OPENROUTER_MODELS", "")
    parsed_models = []

    for model_name in raw_value.split(","):
        cleaned_model_name = model_name.strip()
        if cleaned_model_name:
            parsed_models.append(cleaned_model_name)

    return parsed_models


def _prettify_creator_name(raw_name: str) -> str:
    normalized_name = raw_name.strip().lower()
    known_creators = {
        "qwen": "Qwen",
        "deepseek": "DeepSeek",
        "google": "Google",
        "microsoft": "Microsoft",
        "meta": "Meta",
    }
    return known_creators.get(normalized_name, raw_name.replace("_", " ").title())


def _prettify_openrouter_segment(segment: str) -> List[str]:
    if not segment:
        return []

    acronyms = {
        "it": "IT",
        "ui": "UI",
        "ux": "UX",
        "api": "API",
    }
    known_words = {
        "qwen": "Qwen",
        "deepseek": "DeepSeek",
        "gemma": "Gemma",
        "coder": "Coder",
    }

    alpha_then_digits = re.fullmatch(r"([a-z]+)(\d+)", segment, flags=re.IGNORECASE)
    if alpha_then_digits is not None:
        word_part, digit_part = alpha_then_digits.groups()
        if len(word_part) == 1:
            return [word_part.upper() + digit_part]
        return [
            known_words.get(word_part.lower(), word_part.capitalize()),
            digit_part,
        ]

    digits_then_alpha = re.fullmatch(r"(\d+)([a-z]+)", segment, flags=re.IGNORECASE)
    if digits_then_alpha is not None:
        digit_part, word_part = digits_then_alpha.groups()
        if len(word_part) <= 2:
            return [digit_part + word_part.upper()]
        return [
            digit_part,
            known_words.get(word_part.lower(), word_part.capitalize()),
        ]

    split_segment = []
    current_token = segment[0]

    for character in segment[1:]:
        previous_character = current_token[-1]
        if previous_character.isalpha() != character.isalpha():
            split_segment.append(current_token)
            current_token = character
        else:
            current_token += character

    split_segment.append(current_token)

    prettified_tokens = []
    for token in split_segment:
        normalized_token = token.lower()
        if normalized_token in acronyms:
            prettified_tokens.append(acronyms[normalized_token])
        elif normalized_token in known_words:
            prettified_tokens.append(known_words[normalized_token])
        elif token.isdigit():
            prettified_tokens.append(token)
        elif token[:-1].isdigit() and token[-1].isalpha():
            prettified_tokens.append(token[:-1] + token[-1].upper())
        elif token[0].isalpha() and token[1:].isdigit():
            prettified_tokens.append(token[0].upper() + token[1:])
        else:
            prettified_tokens.append(token.capitalize())

    return prettified_tokens


def prettify_openrouter_model_name(openrouter_model_name: str) -> str:
    model_slug = openrouter_model_name
    if model_slug.endswith(":free"):
        model_slug = model_slug[: -len(":free")]

    model_slug = model_slug.split("/")[-1]
    normalized_slug = model_slug.replace("_", "-")
    segments = [segment for segment in normalized_slug.split("-") if segment]

    if not segments:
        return openrouter_model_name

    prettified_segments = []
    for segment in segments:
        prettified_segments.extend(_prettify_openrouter_segment(segment))

    if not prettified_segments:
        return openrouter_model_name

    return " ".join(prettified_segments)


def build_openrouter_model_catalog() -> List[dict]:
    catalog = []

    for configured_model in parse_openrouter_models():
        if not configured_model.endswith(":free"):
            logger.warning(
                "Skipping OpenRouter model '%s' because only :free models are allowed.",
                configured_model,
            )
            continue

        internal_model_id = f"{OPENROUTER_MODEL_PREFIX}{configured_model}"
        catalog.append(
            {
                "id": internal_model_id,
                "display_name": prettify_openrouter_model_name(configured_model),
                "provider": "openrouter",
                "model_creator": _prettify_creator_name(configured_model.split("/")[0])
                if "/" in configured_model
                else "Unknown",
                "api_provider": "OpenRouter",
                "description": get_model_description(
                    internal_model_id,
                    GENERIC_OPENROUTER_DESCRIPTION,
                ),
                "provider_type": "model_router",
            }
        )

    return catalog


def _build_adapter_response(model_name: str, raw_response: str) -> Dict[str, str]:
    return {
        "model_name": model_name,
        "raw_response": raw_response,
    }


def _parse_openrouter_error_payload(response_text: str) -> dict:
    try:
        parsed_error = json.loads(response_text)
    except (TypeError, json.JSONDecodeError):
        return {}

    if isinstance(parsed_error, dict):
        return parsed_error

    return {}


def _extract_openrouter_error_message(error_payload: dict, response_text: str) -> str:
    if isinstance(error_payload.get("error"), dict):
        message = error_payload["error"].get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    if isinstance(error_payload.get("error"), str) and error_payload["error"].strip():
        return error_payload["error"].strip()

    return response_text.strip()


def _extract_openrouter_suggested_model(message: str) -> str:
    match = re.search(
        r"use this slug instead:\s*([a-z0-9_.-]+/[a-z0-9_.:-]+)",
        message,
        flags=re.IGNORECASE,
    )
    if match is None:
        return ""

    return match.group(1).strip()


def _is_openrouter_model_unavailable(status_code: int, message: str) -> bool:
    normalized_message = message.lower()
    unavailable_markers = (
        "model is unavailable for free",
        "no endpoints found",
        "model not found",
        "invalid model",
        "unavailable",
    )

    if status_code == 404:
        return True

    return any(marker in normalized_message for marker in unavailable_markers)


def _format_openrouter_unavailable_error(
    configured_model: str,
    status_code: int,
    message: str,
) -> str:
    suggested_model = _extract_openrouter_suggested_model(message)
    lines = [
        "Adapter Error",
        "",
        "Model unavailable",
        "",
        "The configured OpenRouter model is no longer available on the free tier.",
        "",
        f"Configured: {configured_model}",
    ]

    if suggested_model:
        suggestion_label = f"{suggested_model} (paid)"
        if suggested_model.endswith(":free"):
            suggestion_label = suggested_model
        lines.extend(
            [
                f"Suggested replacement: {suggestion_label}",
            ]
        )

    lines.extend(
        [
            f"Provider: OpenRouter",
            f"HTTP status: {status_code}",
        ]
    )
    return "\n".join(lines)


def build_openrouter_unavailable_payload(
    configured_model: str,
    status_code: int,
    response_text: str,
) -> dict:
    error_payload = _parse_openrouter_error_payload(response_text)
    message = _extract_openrouter_error_message(error_payload, response_text)
    suggested_model = _extract_openrouter_suggested_model(message) or None

    return {
        "status": "Model Unavailable",
        "short_message": "The configured OpenRouter model is no longer available on the free tier.",
        "configured_model": configured_model,
        "suggested_model": suggested_model,
        "provider": "OpenRouter",
        "http_status": status_code,
    }


def _normalize_openrouter_http_error(
    configured_model: str,
    status_code: int,
    response_text: str,
) -> str:
    parsed_error = _parse_openrouter_error_payload(response_text)
    message = _extract_openrouter_error_message(parsed_error, response_text)

    if _is_openrouter_model_unavailable(status_code, message):
        unavailable_payload = build_openrouter_unavailable_payload(
            configured_model=configured_model,
            status_code=status_code,
            response_text=response_text,
        )
        return _format_openrouter_unavailable_error(
            configured_model=unavailable_payload["configured_model"],
            status_code=unavailable_payload["http_status"],
            message=message,
        )

    return (
        f"OpenRouter request failed with status {status_code}: "
        f"{response_text}"
    )


def run_gemini(problem_prompt: str, model_name: str) -> Dict[str, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "Gemini API key is not configured. Set GEMINI_API_KEY to use Gemini models."
        )

    provider_timeout_seconds = get_provider_request_timeout_seconds()
    gemini_timeout_milliseconds = get_gemini_timeout_milliseconds(
        provider_timeout_seconds
    )

    try:
        genai = importlib.import_module("google.genai")
    except ImportError as error:
        raise ValueError(
            "The google-genai package is not installed. "
            "Run 'pip install -r requirements.txt' to enable Gemini support."
        ) from error

    try:
        client = genai.Client(
            api_key=api_key,
            http_options=genai.types.HttpOptions(
                timeout=gemini_timeout_milliseconds
            ),
        )
        response = client.models.generate_content(
            model=model_name,
            contents=problem_prompt,
        )
    except Exception as error:  # pragma: no cover
        if _is_timeout_error(error):
            raise ValueError(
                "Gemini request timed out after "
                f"{provider_timeout_seconds} seconds."
            ) from error
        raise ValueError(f"Gemini request failed: {error}") from error

    raw_response = getattr(response, "text", None)
    if not raw_response:
        raise ValueError("Gemini returned an empty response.")

    return _build_adapter_response(model_name, raw_response)


def run_groq(problem_prompt: str, model_name: str) -> Dict[str, str]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "Groq API key is not configured. Set GROQ_API_KEY to use Groq models."
        )

    provider_timeout_seconds = get_provider_request_timeout_seconds()

    try:
        requests = importlib.import_module("requests")
    except ImportError as error:
        raise ValueError(
            "The requests package is not installed. "
            "Run 'pip install -r requirements.txt' to enable Groq support."
        ) from error

    groq_model_name = GROQ_MODELS[model_name]

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": groq_model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": problem_prompt,
                    }
                ],
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=provider_timeout_seconds,
        )
    except requests.RequestException as error:
        if "timeout" in type(error).__name__.lower() or "timed out" in str(error).lower():
            raise ValueError(
                "Groq request timed out after "
                f"{provider_timeout_seconds} seconds."
            ) from error
        raise ValueError(
            "Groq request failed. Make sure GROQ_API_KEY is valid and the Groq API is reachable."
        ) from error

    if response.status_code != 200:
        raise ValueError(
            f"Groq request failed with status {response.status_code}: "
            f"{response.text}"
        )

    data = response.json()
    raw_response = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not raw_response:
        raise ValueError("Groq returned an empty response.")

    return _build_adapter_response(model_name, raw_response)


def run_mistral(problem_prompt: str, model_name: str) -> Dict[str, str]:
    api_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "Mistral API key is not configured. Set MISTRAL_API_KEY to use Mistral models."
        )

    provider_timeout_seconds = get_provider_request_timeout_seconds()

    try:
        requests = importlib.import_module("requests")
    except ImportError as error:
        raise ValueError(
            "The requests package is not installed. "
            "Run 'pip install -r requirements.txt' to enable Mistral support."
        ) from error

    mistral_model_name = MISTRAL_MODELS[model_name]

    try:
        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            json={
                "model": mistral_model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": problem_prompt,
                    }
                ],
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=provider_timeout_seconds,
        )
    except requests.RequestException as error:
        if "timeout" in type(error).__name__.lower() or "timed out" in str(error).lower():
            raise ValueError(
                "Mistral request timed out after "
                f"{provider_timeout_seconds} seconds."
            ) from error
        raise ValueError(
            "Mistral request failed. Make sure MISTRAL_API_KEY is valid and the Mistral API is reachable."
        ) from error

    if response.status_code != 200:
        raise ValueError(
            f"Mistral request failed with status {response.status_code}: "
            f"{response.text}"
        )

    data = response.json()
    raw_response = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not raw_response:
        raise ValueError("Mistral returned an empty response.")

    return _build_adapter_response(model_name, raw_response)


def run_openrouter(problem_prompt: str, model_name: str) -> Dict[str, str]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "OpenRouter API key is not configured. Set OPENROUTER_API_KEY to use OpenRouter models."
        )

    provider_timeout_seconds = get_provider_request_timeout_seconds()

    try:
        requests = importlib.import_module("requests")
    except ImportError as error:
        raise ValueError(
            "The requests package is not installed. "
            "Run 'pip install -r requirements.txt' to enable OpenRouter support."
        ) from error

    openrouter_model_name = model_name.removeprefix(OPENROUTER_MODEL_PREFIX)

    try:
        response = requests.post(
            OPENROUTER_API_URL,
            json={
                "model": openrouter_model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": problem_prompt,
                    }
                ],
                "temperature": 0,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=provider_timeout_seconds,
        )
    except requests.RequestException as error:
        if "timeout" in type(error).__name__.lower() or "timed out" in str(error).lower():
            raise ValueError(
                "OpenRouter request timed out after "
                f"{provider_timeout_seconds} seconds."
            ) from error
        raise ValueError(
            "OpenRouter request failed. Make sure OPENROUTER_API_KEY is valid and the OpenRouter API is reachable."
        ) from error

    if response.status_code != 200:
        raise ValueError(
            _normalize_openrouter_http_error(
                configured_model=openrouter_model_name,
                status_code=response.status_code,
                response_text=response.text,
            )
        )

    data = response.json()
    raw_response = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not raw_response:
        raise ValueError("OpenRouter returned an empty response.")

    return _build_adapter_response(model_name, raw_response)


def get_model_provider_registry() -> Dict[str, ProviderFunction]:
    registry: Dict[str, ProviderFunction] = {
        "gemini-flash-latest": run_gemini,
        "groq:llama-3.3-70b-versatile": run_groq,
        "mistral:mistral-small-latest": run_mistral,
    }

    for configured_model in parse_openrouter_models():
        if configured_model.endswith(":free"):
            registry[f"{OPENROUTER_MODEL_PREFIX}{configured_model}"] = run_openrouter

    return registry


def generate_solution(
    problem_prompt: str,
    model_name: str = "gemini-flash-latest",
) -> Dict[str, str]:
    provider_registry = get_model_provider_registry()
    provider = provider_registry.get(model_name)

    if provider is None:
        supported_models = ", ".join(sorted(provider_registry))
        raise ValueError(
            f"Unsupported model_name: {model_name}. "
            f"Supported models: {supported_models}"
        )

    return provider(problem_prompt, model_name)
