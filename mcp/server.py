"""MCP server for the AmoCRM Sales Assistant (stdio transport).

Three tools proxy the running HTTP API, so an MCP client exercises exactly
the same backend the demo UI uses (no second implementation):

  get_health     — app + Ollama status (prerequisite check for a run)
  retrieve_kb    — instant BM25 matches, scores, threshold, language
  assist_manager — full dual output: customer reply + internal sales hints
"""

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")

mcp = FastMCP("amocrm-sales-assistant")

ASSIST_TIMEOUT = 180.0


def _check_lang(ui_lang: str) -> None:
    if ui_lang not in {"ru", "en"}:
        raise ValueError("ui_lang must be 'ru' or 'en'")


async def _post(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{BASE_URL}{path}", json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"{path} -> HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


@mcp.tool()
async def get_health() -> dict[str, Any]:
    """App + Ollama status. Call this first: the app must be up (`make up`)
    and Ollama reachable (`make warmup`) for assist_manager to use the LLM."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{BASE_URL}/api/health")
    if resp.status_code >= 400:
        raise RuntimeError(f"/api/health -> HTTP {resp.status_code}")
    return resp.json()


@mcp.tool()
async def retrieve_kb(
    message: str,
    ui_lang: str = "ru",
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """BM25 retrieval over the knowledge base (no LLM involved).

    Returns detected_lang, lang_source (message|conversation|ui_default),
    top-3 matches with scores and matched terms, threshold and grounded
    (true = top score >= threshold, i.e. the LLM may answer from the KB).
    """
    _check_lang(ui_lang)
    return await _post(
        "/api/retrieve",
        {"message": message, "ui_lang": ui_lang, "history": history or []},
        timeout=30.0,
    )


@mcp.tool()
async def assist_manager(
    message: str,
    ui_lang: str = "ru",
    history: list[dict[str, str]] | None = None,
    deal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full dual output for a customer message through the real pipeline.

    customer_reply (customer-facing, in the customer's language, kb_refs
    filled from retrieval) and internal_sales_hints (manager's UI language,
    upsell/cross-sell chosen by the deterministic rule engine) are two
    independent contracts. Also returns retrieval matches, intent and
    validation flags (schema/language/numbers/leakage, fallback_used,
    model, latency_ms). Ungrounded messages skip the LLM and return the
    honest templated fallback.
    """
    _check_lang(ui_lang)
    return await _post(
        "/api/assist",
        {"message": message, "ui_lang": ui_lang, "history": history or [], "deal": deal or {}},
        timeout=ASSIST_TIMEOUT,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
