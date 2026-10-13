import os
import re
import logging
from pathlib import Path

from dotenv import load_dotenv
import httpx
from ollama import Client
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

def generate_with_ollama(prompt: str) -> str:
    model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    client_options = {"timeout": _timeout_seconds("OLLAMA_TIMEOUT_SECONDS")}
    host = os.getenv("OLLAMA_HOST")
    if host:
        client_options["host"] = host
    client = Client(**client_options)
    chat_options = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "options": {
            "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192")),
            "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "4096")),
        },
        "format": "json",
    }
    if model.startswith("qwen3"):
        chat_options["think"] = False
    response = client.chat(**chat_options)
    return _clean_json_response(response.message.content)


# =========================================================
# GROQCLOUD
# =========================================================

def generate_with_groq(prompt: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured in .env")

    client = Groq(api_key=api_key, timeout=_timeout_seconds("GROQ_TIMEOUT_SECONDS"), max_retries=0)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "550")),
        response_format={"type": "json_object"},
    )
    return _clean_json_response(response.choices[0].message.content)


# =========================================================
# GOOGLE GEMINI
# =========================================================

def generate_with_gemini(prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY is not configured in .env")

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
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
        else:
            raise ValueError("For hybrid provider, task must be 'research' or 'proposal'.")

        if selected_provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported hybrid provider: {selected_provider}")
        return selected_provider

    raise ValueError(f"Unsupported LLM provider: {provider}")


def _generate_with(provider: str, prompt: str) -> str:
    if provider == "ollama":
        return generate_with_ollama(prompt)
    if provider == "groq":
        return generate_with_groq(prompt)
    if provider == "gemini":
        return generate_with_gemini(prompt)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def generate(prompt: str, task: str = None) -> str:
    primary = _provider_for_task(task)
    fallback = os.getenv("LLM_FALLBACK_PROVIDER", "").strip().lower()

    try:
        return _generate_with(primary, prompt)
    except Exception as primary_error:
        if fallback not in SUPPORTED_PROVIDERS or fallback == primary:
            raise

        logger.warning("Primary LLM provider %s failed; trying configured fallback %s", primary, fallback)
        try:
            return _generate_with(fallback, prompt)
        except Exception as fallback_error:
            raise RuntimeError(
                f"Primary provider {primary} failed ({primary_error}); "
                f"fallback provider {fallback} failed ({fallback_error})"
            ) from fallback_error
