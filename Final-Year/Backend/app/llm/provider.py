import os
import logging
from pathlib import Path

from dotenv import load_dotenv
import httpx
from ollama import Client, ResponseError
from groq import Groq


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _timeout_seconds(setting: str) -> float:
    try:
        return float(os.getenv(setting, os.getenv("LLM_TIMEOUT_SECONDS", "90")))
    except ValueError as error:
        raise ValueError(f"{setting} must be a number") from error


def _clean_json_response(raw_text: str) -> str:
    """Strip markdown code fence blocks if returned by the LLM."""
    text = (raw_text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


# =========================================================
# OLLAMA
# =========================================================

def _ollama_chat(
    client: Client,
    model: str,
    prompt: str,
    *,
    task: str | None = None,
) -> str:
    predict_setting = (
        "OLLAMA_RESEARCH_NUM_PREDICT"
        if task == "research"
        else "OLLAMA_EMAIL_NUM_PREDICT"
        if task == "email"
        else "OLLAMA_NUM_PREDICT"
    )
    context_setting = (
        "OLLAMA_RESEARCH_NUM_CTX"
        if task == "research"
        else "OLLAMA_EMAIL_NUM_CTX"
        if task == "email"
        else "OLLAMA_NUM_CTX"
    )
    chat_options = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "options": {
            "num_ctx": int(os.getenv(context_setting, "8192")),
            "num_predict": int(os.getenv(predict_setting, "2048")),
        },
        "format": "json",
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
    }
    if model.startswith("qwen3"):
        chat_options["think"] = False
    response = client.chat(**chat_options)
    return _clean_json_response(response.message.content)


def generate_with_ollama(prompt: str, *, task: str | None = None) -> str:
    model_setting = (
        "OLLAMA_RESEARCH_MODEL"
        if task == "research"
        else "OLLAMA_EMAIL_MODEL"
        if task == "email"
        else "OLLAMA_MODEL"
    )
    configured_model = os.getenv(model_setting, "").strip()
    default_model = "qwen3:14b"
    model = configured_model or default_model
    client_options = {"timeout": _timeout_seconds("OLLAMA_TIMEOUT_SECONDS")}
    host = os.getenv("OLLAMA_HOST")
    if host:
        client_options["host"] = host
    client = Client(**client_options)
    try:
        return _ollama_chat(client, model, prompt, task=task)
    except ResponseError as error:
        if error.status_code != 404:
            raise
        if configured_model:
            raise RuntimeError(
                f"Configured Ollama model '{model}' is not installed. "
                f"Run 'ollama pull {model}' or set OLLAMA_MODEL to an installed model."
            ) from error

    try:
        installed_models = client.list().models
    except Exception as error:
        raise RuntimeError(
            f"Default Ollama model '{model}' is not installed and installed models "
            f"could not be listed. Run 'ollama pull {model}' or set {model_setting}."
        ) from error

    installed_model_names = {
        item.model for item in installed_models
        if isinstance(item.model, str)
    }
    compatible_models = sorted(
        name for name in installed_model_names if name.startswith("qwen3:")
    )
    if "phi3:latest" not in installed_model_names and not compatible_models:
        raise RuntimeError(
            f"Default Ollama model '{model}' is not installed, and no Qwen 3 model "
            f"or phi3:latest model is available locally. Run 'ollama pull {model}' "
            f"or set {model_setting} to an installed model."
        )

    if "phi3:latest" in installed_model_names:
        fallback_model = "phi3:latest"
    elif "qwen3:14b" in compatible_models:
        fallback_model = "qwen3:14b"
    else:
        fallback_model = compatible_models[0]
    logger.warning(
        "Default Ollama model %s is not installed; using installed compatible model %s",
        model,
        fallback_model,
    )
    try:
        return _ollama_chat(client, fallback_model, prompt, task=task)
    except ResponseError as error:
        raise RuntimeError(
            f"Default Ollama model '{model}' is missing and installed fallback "
            f"'{fallback_model}' could not generate a response: {error}"
        ) from error


# =========================================================
# GROQCLOUD
# =========================================================

def generate_with_groq(prompt: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured in .env")

    client = Groq(api_key=api_key, timeout=_timeout_seconds("GROQ_TIMEOUT_SECONDS"), max_retries=0)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=int(os.getenv("GROQ_MAX_TOKENS", "4096")),
        reasoning_effort=os.getenv("GROQ_REASONING_EFFORT", "low"),
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError(
            f"Groq model '{model}' returned an empty response. Increase GROQ_MAX_TOKENS "
            "or lower GROQ_REASONING_EFFORT."
        )
    return _clean_json_response(content)


# =========================================================
# GOOGLE GEMINI
# =========================================================

def generate_with_gemini(prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY is not configured in .env")

    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }
    timeout = _timeout_seconds("GEMINI_TIMEOUT_SECONDS")
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("Gemini returned no candidates.")
        content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return _clean_json_response(content)


def generate_with_gemini_google_search(prompt: str) -> tuple[str, list[dict[str, str]]]:
    """Generate grounded research with Google's web search tool and return citations."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Set GEMINI_API_KEY to enable Google Search grounded research.")
    model = os.getenv("GEMINI_RESEARCH_MODEL", os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2},
    }
    with httpx.Client(timeout=_timeout_seconds("GEMINI_TIMEOUT_SECONDS")) as client:
        response = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        response.raise_for_status()
        data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini Google Search returned no candidates.")
    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    content = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    metadata = candidate.get("groundingMetadata", {})
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for chunk in metadata.get("groundingChunks", []) if isinstance(metadata, dict) else []:
        web = chunk.get("web", {}) if isinstance(chunk, dict) else {}
        uri, title = web.get("uri"), web.get("title")
        if isinstance(uri, str) and uri.startswith(("https://", "http://")) and uri not in seen:
            seen.add(uri)
            sources.append({"title": title if isinstance(title, str) else uri, "url": uri})
    return _clean_json_response(content), sources[:20]


# =========================================================
# PROVIDER ROUTING
# =========================================================

SUPPORTED_PROVIDERS = {"ollama", "groq", "gemini"}


def _provider_for_task(task: str = None) -> str:
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider in SUPPORTED_PROVIDERS:
        return provider

    if provider == "hybrid":
        if task == "research":
            selected_provider = os.getenv("RESEARCH_PROVIDER", "groq").lower()
        elif task == "proposal":
            selected_provider = os.getenv("PROPOSAL_PROVIDER", "groq").lower()
        elif task == "email":
            selected_provider = os.getenv("EMAIL_PROVIDER", "groq").lower()
        else:
            raise ValueError("For hybrid provider, task must be 'research', 'proposal', or 'email'.")

        if selected_provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported hybrid provider: {selected_provider}")
        return selected_provider

    raise ValueError(f"Unsupported LLM provider: {provider}")


def _generate_with(provider: str, prompt: str, task: str | None = None) -> str:
    if provider == "ollama":
        return generate_with_ollama(prompt, task=task)
    if provider == "groq":
        return generate_with_groq(prompt)
    if provider == "gemini":
        return generate_with_gemini(prompt)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def generate(prompt: str, task: str = None) -> str:
    primary = _provider_for_task(task)
    # Email drafting should remain available when its cloud provider is down.
    # Keep this override configurable, but default email generation to local Ollama.
    fallback = (
        os.getenv("EMAIL_FALLBACK_PROVIDER", "ollama").strip().lower()
        if task == "email"
        else os.getenv("LLM_FALLBACK_PROVIDER", "").strip().lower()
    )

    try:
        return _generate_with(primary, prompt, task)
    except Exception as primary_error:
        if fallback not in SUPPORTED_PROVIDERS or fallback == primary:
            raise

        logger.warning("Primary LLM provider %s failed; trying configured fallback %s", primary, fallback)
        try:
            return _generate_with(fallback, prompt, task)
        except Exception as fallback_error:
            raise RuntimeError(
                f"Primary provider {primary} failed ({primary_error}); "
                f"fallback provider {fallback} failed ({fallback_error})"
            ) from fallback_error
