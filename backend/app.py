import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException

from backend.language import detect_language
from backend.models import MatchOut, RetrieveRequest, RetrieveResponse
from backend.retriever import get_retriever

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
KB_PATH = Path(__file__).resolve().parent.parent / "kb" / "kb.json"

app = FastAPI(title="AmoCRM Sales Assistant", version="1.0.0")


def _ollama_status() -> tuple[str, list[str]]:
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3.0)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return "reachable", models
    except Exception:
        return "unreachable", []


def _kb_entry_count() -> int:
    if not KB_PATH.exists():
        return 0
    data = json.loads(KB_PATH.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("entries", [])
    return len(entries)


@app.get("/api/health")
def health() -> dict:
    ollama, models = _ollama_status()
    return {
        "status": "ok",
        "ollama": ollama,
        "models_present": models,
        "kb_entries": _kb_entry_count(),
    }


@app.post("/api/retrieve", response_model=RetrieveResponse)
def retrieve(req: RetrieveRequest) -> RetrieveResponse:
    """Instant BM25 retrieval shared with /api/assist (CONTEXT §4a)."""
    history = [m.model_dump() for m in req.history]
    lang, lang_source = detect_language(req.message, history, req.ui_lang)
    try:
        matches, threshold, grounded = get_retriever().retrieve(req.message)
    except Exception as exc:  # KB unreadable — surface as 503, not a crash
        raise HTTPException(status_code=503, detail="kb_unavailable") from exc

    return RetrieveResponse(
        detected_lang=lang,
        lang_source=lang_source,
        matches=[
            MatchOut(
                id=m.entry.id,
                title=getattr(m.entry.title, req.ui_lang),
                score=m.score,
                matched_terms=m.matched_terms,
            )
            for m in matches
        ],
        threshold=threshold,
        grounded=grounded,
    )
