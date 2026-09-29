import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI

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
