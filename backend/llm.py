"""Ollama chat client with JSON-Schema structured output (CONTEXT §17).

Model config comes from env: OLLAMA_BASE_URL, LLM_MODEL, LLM_FALLBACK_MODEL,
LLM_TIMEOUT_S. Primary model failure (timeout/unreachable) falls back once
to the smaller model.
"""

import json
import os
from typing import Any

import httpx
from pydantic import BaseModel, Field

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
PRIMARY_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "qwen2.5:3b")
TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "45"))

# JSON Schema passed to Ollama's `format` parameter (CONTEXT §17).
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["customer_reply", "upsell_reasons", "cross_sell_reasons"],
    "properties": {
        "customer_reply": {"type": "string"},
        "upsell_reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "reason", "talking_point"],
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": "string"},
                    "talking_point": {"type": "string"},
                },
            },
        },
        "cross_sell_reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "reason", "talking_point"],
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": "string"},
                    "talking_point": {"type": "string"},
                },
            },
        },
    },
}


class LlmUnavailable(Exception):
    """Ollama unreachable, timed out, or returned an error status."""


class LlmUnparsable(Exception):
    """Model output was not valid JSON (schema validator will retry once)."""


class Reason(BaseModel):
    id: str
    reason: str
    talking_point: str


class LlmOutput(BaseModel):
    customer_reply: str
    upsell_reasons: list[Reason] = Field(default_factory=list)
    cross_sell_reasons: list[Reason] = Field(default_factory=list)


def build_payload(messages: list[dict[str, str]], model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.2, "seed": 42, "num_ctx": 4096},
        "format": OUTPUT_SCHEMA,
    }


def chat_raw(messages: list[dict[str, str]], model: str) -> str:
    """One non-streaming structured call. Raises LlmUnavailable on any transport issue."""
    payload = build_payload(messages, model)
    try:
        resp = httpx.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=TIMEOUT_S)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
    except (httpx.HTTPError, ValueError) as exc:
        raise LlmUnavailable(f"{model}: {exc}") from exc
    if not content:
        raise LlmUnavailable(f"{model}: empty response")
    return content


def generate(messages: list[dict[str, str]], model: str | None = None) -> tuple[dict, str]:
    """Returns (parsed_output, model_used).

    Tries the primary model first; on timeout/unreachable falls back once
    to the smaller model (§13: retry with qwen2.5:3b).
    """
    primary = model or PRIMARY_MODEL
    try:
        return _parse(chat_raw(messages, primary)), primary
    except LlmUnavailable as first_error:
        if primary == FALLBACK_MODEL:
            raise
        try:
            return _parse(chat_raw(messages, FALLBACK_MODEL)), FALLBACK_MODEL
        except LlmUnavailable as second_error:
            raise LlmUnavailable(f"primary: {first_error}; fallback: {second_error}") from second_error


def _parse(content: str) -> dict:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LlmUnparsable(f"not JSON: {content[:200]}") from exc
    if not isinstance(parsed, dict):
        raise LlmUnparsable(f"expected object, got {type(parsed).__name__}")
    return parsed
