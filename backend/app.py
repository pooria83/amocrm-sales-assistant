import json
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException

from backend.fallback import (
    no_match_note,
    no_match_reply,
    templated_reason,
    validation_failed_reply,
)
from backend.kb import get_kb
from backend.language import detect_language
from backend.llm import (
    LlmOutput,
    LlmUnavailable,
    Reason,
    build_messages,
    generate,
)
from backend.models import (
    AssistRequest,
    AssistResponse,
    CustomerReplyOut,
    HintItemOut,
    InternalSalesHintsOut,
    MatchOut,
    RetrievalOut,
    RetrieveRequest,
    RetrieveResponse,
    ValidationOut,
)
from backend.retriever import Match, get_retriever
from backend.rules import Candidate, detect_intent, find_candidates
from backend.validators import (
    Validation,
    check_language,
    check_leakage,
    check_length,
    check_numbers,
    enforce_candidates,
    parse_output,
)

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


def _match_out(match: Match, ui_lang: str) -> MatchOut:
    return MatchOut(
        id=match.entry.id,
        title=getattr(match.entry.title, ui_lang),
        score=match.score,
        matched_terms=match.matched_terms,
    )


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
        matches=[_match_out(m, req.ui_lang) for m in matches],
        threshold=threshold,
        grounded=grounded,
    )


# ---------------------------------------------------------------------------
# /api/assist — full dual-output orchestration (CONTEXT §13, §4a)
# ---------------------------------------------------------------------------

def _with_reminder(messages: list[dict[str, str]], problems: list[str]) -> list[dict[str, str]]:
    reminder = (
        "Your previous reply failed validation:\n- "
        + "\n- ".join(problems[:6])
        + "\nFix these issues and return only the corrected JSON object."
    )
    return messages + [{"role": "user", "content": reminder}]


def _hint_items(
    candidates: list[Candidate],
    ui_lang: str,
    reason_by_id: dict[str, Reason] | None = None,
) -> list[HintItemOut]:
    titles = {entry.id: entry for entry in get_kb()}
    items: list[HintItemOut] = []
    for candidate in candidates:
        entry = titles.get(candidate.id)
        title = getattr(entry.title, ui_lang) if entry else candidate.id
        reason = reason_by_id.get(candidate.id) if reason_by_id else None
        if reason is not None:
            items.append(
                HintItemOut(
                    id=candidate.id,
                    title=title,
                    reason=reason.reason,
                    talking_point=reason.talking_point,
                )
            )
        else:
            templated_text, talking_point = templated_reason(candidate.rule, ui_lang)
            items.append(
                HintItemOut(
                    id=candidate.id,
                    title=title,
                    reason=templated_text,
                    talking_point=talking_point,
                )
            )
    return items


def _validation_out(
    base: Validation, *, retries: int, fallback_used: bool, model: str, latency_ms: int
) -> ValidationOut:
    return ValidationOut(
        numbers_ok=base.numbers_ok,
        language_ok=base.language_ok,
        no_leakage=base.no_leakage,
        schema_ok=base.schema_ok,
        retries=retries,
        fallback_used=fallback_used,
        model=model,
        latency_ms=latency_ms,
    )


def _template_validation() -> Validation:
    """Templates pass every check by construction (§18)."""
    return Validation(
        schema_ok=True, candidates_ok=True, language_ok=True, numbers_ok=True,
        no_leakage=True, length_ok=True,
    )


@app.post("/api/assist", response_model=AssistResponse)
def assist(req: AssistRequest) -> AssistResponse:
    started = time.monotonic()
    history = [m.model_dump() for m in req.history]
    deal = req.deal
    lang, _ = detect_language(req.message, history, req.ui_lang)

    try:
        matches, threshold, grounded = get_retriever().retrieve(req.message)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="kb_unavailable") from exc

    retrieval = RetrievalOut(
        matches=[_match_out(m, req.ui_lang) for m in matches], threshold=threshold
    )

    intent = detect_intent(req.message)

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    # Ungrounded: skip rule engine and LLM entirely, honest template (§4a, §18).
    if not grounded:
        return AssistResponse(
            detected_lang=lang,
            intent=intent,
            grounded=False,
            customer_reply=CustomerReplyOut(
                text=no_match_reply(lang, deal.contact), lang=lang, kb_refs=[]
            ),
            internal_sales_hints=InternalSalesHintsOut(
                lang=req.ui_lang, upsell=[], cross_sell=[], notes=no_match_note(req.ui_lang)
            ),
            retrieval=retrieval,
            validation=_validation_out(
                _template_validation(), retries=0, fallback_used=True, model="",
                latency_ms=elapsed(),
            ),
        )

    candidates = find_candidates(matches, intent, deal, req.message)
    kb_refs = [m.entry.id for m in matches if m.score >= threshold]

    messages = build_messages(
        message=req.message,
        history=history,
        matches=matches,
        candidates=candidates,
        deal=deal,
        customer_lang=lang,
        ui_lang=req.ui_lang,
    )

    final_output: LlmOutput | None = None
    validation = Validation()
    attempt_errors: list[str] = []
    model_used = ""
    retries = 0

    for attempt in range(2):
        if attempt > 0:
            retries = 1
            messages = _with_reminder(messages, attempt_errors)
        try:
            parsed, model_used = generate(messages)
        except LlmUnavailable as exc:
            attempt_errors = [f"llm_unavailable: {exc}"]
            break

        output = parse_output(parsed)
        if output is None:
            attempt_errors = ["schema_ok failed: response did not match the JSON shape"]
            continue

        cleaned, candidate_problems = enforce_candidates(output, candidates)
        numbers_ok, _claims = check_numbers(
            cleaned.customer_reply, matches=matches, deal=deal, customer_message=req.message
        )
        lang_ok = check_language(cleaned.customer_reply, lang)
        leaks = check_leakage(cleaned, candidates)
        length_ok = check_length(cleaned.customer_reply)

        problems = list(candidate_problems)
        if not lang_ok:
            problems.append(f"language_ok failed: reply is not {lang}")
        if not numbers_ok:
            problems.append("numbers_ok failed: unsupported numeric claim")
        problems += leaks
        if not length_ok:
            problems.append("length_ok failed: reply empty or over 600 chars")

        validation = Validation(
            schema_ok=True,
            candidates_ok=not candidate_problems,
            language_ok=lang_ok,
            numbers_ok=numbers_ok,
            no_leakage=not leaks,
            length_ok=length_ok,
            errors=problems,
        )
        if not problems:
            final_output = cleaned
            break
        attempt_errors = problems

    if final_output is not None:
        reason_by_id = {
            r.id: r for r in final_output.upsell_reasons + final_output.cross_sell_reasons
        }
        return AssistResponse(
            detected_lang=lang,
            intent=intent,
            grounded=True,
            customer_reply=CustomerReplyOut(
                text=final_output.customer_reply, lang=lang, kb_refs=kb_refs
            ),
            internal_sales_hints=InternalSalesHintsOut(
                lang=req.ui_lang,
                upsell=_hint_items(candidates.upsell, req.ui_lang, reason_by_id),
                cross_sell=_hint_items(candidates.cross_sell, req.ui_lang, reason_by_id),
                notes="",
            ),
            retrieval=retrieval,
            validation=_validation_out(
                validation, retries=retries, fallback_used=False, model=model_used,
                latency_ms=elapsed(),
            ),
        )

    # LLM unavailable or invalid twice: templated reply + templated reasons (§18)
    if not validation.schema_ok:
        validation = _template_validation()
        validation.errors = attempt_errors
    return AssistResponse(
        detected_lang=lang,
        intent=intent,
        grounded=True,
        customer_reply=CustomerReplyOut(
            text=validation_failed_reply(lang, deal.contact), lang=lang, kb_refs=kb_refs
        ),
        internal_sales_hints=InternalSalesHintsOut(
            lang=req.ui_lang,
            upsell=_hint_items(candidates.upsell, req.ui_lang),
            cross_sell=_hint_items(candidates.cross_sell, req.ui_lang),
            notes="",
        ),
        retrieval=retrieval,
        validation=_validation_out(
            validation, retries=retries, fallback_used=True, model=model_used,
            latency_ms=elapsed(),
        ),
    )


# Serve the built frontend (npm --prefix frontend run build → frontend/dist),
# so one uvicorn/docker process hosts the whole app. Mounted last so it never
# shadows the /api routes above.
_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_DIST_DIR, html=True), name="frontend")
