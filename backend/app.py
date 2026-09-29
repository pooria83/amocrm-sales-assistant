import json
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException

from backend.fallback import (
    no_match_note,
    no_match_reply,
    pricing_fallback_reply,
    templated_reason,
    validation_failed_reply,
)
from backend.kb import get_kb
from backend.language import detect_language
from backend.llm import (
    LlmOutput,
    LlmUnavailable,
    LlmUnparsable,
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
    check_manager_referral,
    check_numbers,
    check_output_script,
    check_plan_capacity,
    check_script,
    enforce_candidates,
    find_bad_claim,
    inapplicable_plans,
    parse_output,
    strip_foreign_percent_sentences,
    strip_percent_denial,
    strip_signoff,
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
KB_PATH = Path(__file__).resolve().parent.parent / "kb" / "kb.json"

# Emit backend/llm.py usage logs (prompt_eval_count/eval_count/load_duration)
# and LLM failures to stdout so `docker compose logs backend` shows them.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

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

def _with_reminder(
    messages: list[dict[str, str]],
    problems: list[str],
    lang: str = "ru",
    prev_reply: str = "",
) -> list[dict[str, str]]:
    """Retry prompt: raw problems + explicit, imperative fixes for the
    failure classes the model kept repeating in MCP run 20260929-202325
    (referral phrases, sign-off placeholders, stray CJK)."""
    joined = "\n".join(problems)
    fixes: list[str] = []
    if "role_ok" in joined:
        fixes.append(
            "Referral removed: you ARE the manager — rewrite in first person "
            "(«Я…») with zero mentions of contacting a manager."
        )
    if "placeholder" in joined or "Your Name" in joined:
        fixes.append(
            "No placeholders or sign-offs: delete [Your Name], [Your Company "
            "Name], «С уважением, …» — end with the answer itself."
        )
    if "script_ok" in joined:
        fixes.append(
            "Script: rewrite customer_reply using ONLY the customer's "
            "language alphabet — remove every foreign (CJK) character."
        )
    if "language_ok" in joined:
        fixes.append(
            f"Language: the customer wrote in {lang.upper()} — translate the "
            f"ENTIRE customer_reply into {lang}, every sentence, no RU text."
        )
    if "numbers_ok" in joined:
        fixes.append(
            "Numbers: quote only values present in <kb> or <deal>, each with "
            "its unit — drop every other number, then state our real <kb> "
            "terms explicitly (do not evade with «я уточню»)."
        )
    if "upgrade pitch" in joined or "add-on content attributed" in joined:
        fixes.append(
            "Titles: delete the sentence offering another plan/add-on, or name "
            "the add-on explicitly — upgrades belong to internal hints only."
        )
    if "length_ok" in joined:
        fixes.append("Length: shorten to 3 sentences (≤450 characters).")
    prev_block = ""
    if prev_reply:
        # Show what failed so the model PATCHES it instead of regenerating
        # from scratch (MCP run 20260929-213144: retries lost the 1-hour
        # fact, the API mention, or flipped language).
        prev_block = (
            "Previous customer_reply (failed validation):\n<previous_reply>"
            + prev_reply
            + "</previous_reply>\nFix ONLY the listed problems — keep every "
            "other sentence, fact and number from it.\n"
        )
    reminder = (
        prev_block
        + "Your previous reply failed validation:\n- "
        + "\n- ".join(problems[:6])
        + "\nRequired fixes:\n"
        + "\n".join(f"- {f}" for f in fixes)
        + "\nReturn ONLY the corrected JSON object with a clean customer_reply."
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
    base: Validation, *, retries: int, fallback_used: bool, model: str, latency_ms: int,
    retrieve_ms: int = 0, prompt_ms: int = 0, llm_ms: list[int] | None = None,
    validate_ms: int = 0,
) -> ValidationOut:
    return ValidationOut(
        numbers_ok=base.numbers_ok,
        capacity_ok=base.capacity_ok,
        language_ok=base.language_ok,
        no_leakage=base.no_leakage,
        schema_ok=base.schema_ok,
        script_ok=base.script_ok,
        role_ok=base.role_ok,
        retries=retries,
        fallback_used=fallback_used,
        model=model,
        latency_ms=latency_ms,
        retrieve_ms=retrieve_ms,
        prompt_ms=prompt_ms,
        llm_ms=llm_ms or [],
        validate_ms=validate_ms,
    )


def _template_validation() -> Validation:
    """Templates pass every check by construction (§18)."""
    return Validation(
        schema_ok=True, candidates_ok=True, language_ok=True, numbers_ok=True,
        capacity_ok=True, script_ok=True, role_ok=True, no_leakage=True,
        length_ok=True,
    )


@app.post("/api/assist", response_model=AssistResponse)
def assist(req: AssistRequest) -> AssistResponse:
    started = time.monotonic()
    history = [m.model_dump() for m in req.history]
    deal = req.deal
    lang, _ = detect_language(req.message, history, req.ui_lang)

    t0 = time.monotonic()
    try:
        matches, threshold, grounded = get_retriever().retrieve(req.message)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="kb_unavailable") from exc
    retrieve_ms = int((time.monotonic() - t0) * 1000)

    retrieval = RetrievalOut(
        matches=[_match_out(m, req.ui_lang) for m in matches], threshold=threshold
    )

    intent = detect_intent(req.message)
    prompt_ms = 0
    llm_ms: list[int] = []
    validate_ms = 0

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    # Ungrounded: skip rule engine and LLM entirely, honest template (§4a, §18).
    if not grounded:
        reply_text = no_match_reply(lang, deal.contact)
        # Task A: a pricing question without a KB match still gets the plan
        # prices — from KB facts only, verified by the numeric guardrail.
        if intent == "pricing":
            candidate_text = pricing_fallback_reply(lang, deal.contact)
            plan_matches = [
                Match(entry=e, score=0.0, matched_terms=[])
                for e in get_kb()
                if e.type == "plan"
            ]
            numbers_ok, _claims = check_numbers(
                candidate_text, matches=plan_matches, deal=deal,
                customer_message=req.message,
            )
            if numbers_ok and not check_script(candidate_text):
                reply_text = candidate_text
        return AssistResponse(
            detected_lang=lang,
            intent=intent,
            grounded=False,
            customer_reply=CustomerReplyOut(
                text=reply_text, lang=lang, kb_refs=[]
            ),
            internal_sales_hints=InternalSalesHintsOut(
                lang=req.ui_lang, upsell=[], cross_sell=[], notes=no_match_note(req.ui_lang)
            ),
            retrieval=retrieval,
            validation=_validation_out(
                _template_validation(), retries=0, fallback_used=True, model="",
                latency_ms=elapsed(), retrieve_ms=retrieve_ms,
            ),
        )

    candidates = find_candidates(matches, intent, deal, req.message)
    kb_refs = [m.entry.id for m in matches if m.score >= threshold]

    # Task B: capacity mismatch — the smallest plan that actually fits the
    # requested headcount is appended to the <kb> passages so the model can
    # answer with its facts (score 0: it is NOT a retrieval match, so kb_refs
    # and the retrieval panel stay unchanged).
    prompt_matches = list(matches)
    capacity, inapplicable = inapplicable_plans(req.message)
    if inapplicable and capacity is not None:
        have = {m.entry.id for m in prompt_matches}

        def _tier_key(entry):
            max_users = entry.facts.get("max_users")
            if isinstance(max_users, int | float):
                return (0, float(max_users))
            return (1, 0.0)

        fitting = [
            e
            for e in get_kb()
            if e.type == "plan"
            and e.id not in have
            and (
                not isinstance(e.facts.get("max_users"), int | float)
                or e.facts["max_users"] >= capacity
            )
        ]
        if fitting:
            prompt_matches = [
                *prompt_matches,
                Match(entry=min(fitting, key=_tier_key), score=0.0, matched_terms=["capacity"]),
            ]

    t0 = time.monotonic()
    messages = build_messages(
        message=req.message,
        history=history,
        matches=prompt_matches,
        candidates=candidates,
        deal=deal,
        customer_lang=lang,
        ui_lang=req.ui_lang,
    )
    prompt_ms = int((time.monotonic() - t0) * 1000)

    final_output: LlmOutput | None = None
    validation = Validation()
    attempt_errors: list[str] = []
    prev_reply = ""
    model_used = ""
    retries = 0

    for attempt in range(2):
        if attempt > 0:
            retries = 1
            messages = _with_reminder(messages, attempt_errors, lang, prev_reply)
        t0 = time.monotonic()
        try:
            parsed, model_used = generate(messages)
        except LlmUnavailable as exc:
            llm_ms.append(int((time.monotonic() - t0) * 1000))
            logger.warning("llm_unavailable attempt=%d: %s", attempt, exc)
            attempt_errors = [f"llm_unavailable: {exc}"]
            break
        except LlmUnparsable as exc:
            # Not valid JSON → same path as a schema failure: one retry, then
            # the templated fallback (§17). Without this the exception escaped
            # as an unhandled HTTP 500.
            llm_ms.append(int((time.monotonic() - t0) * 1000))
            logger.warning(
                "assist unparsable attempt=%d message=%r: %s",
                attempt, req.message[:80], str(exc)[:200],
            )
            attempt_errors = [f"schema_ok failed: {exc}"]
            continue
        llm_ms.append(int((time.monotonic() - t0) * 1000))

        t0 = time.monotonic()
        output = parse_output(parsed)
        if output is None:
            attempt_errors = ["schema_ok failed: response did not match the JSON shape"]
            validate_ms += int((time.monotonic() - t0) * 1000)
            continue

        cleaned, candidate_problems = enforce_candidates(
            output, candidates, ui_lang=req.ui_lang
        )
        cleaned.customer_reply = strip_signoff(
            strip_percent_denial(cleaned.customer_reply)
        )
        cleaned.customer_reply = strip_foreign_percent_sentences(
            cleaned.customer_reply,
            matches=prompt_matches,
            deal=deal,
            customer_message=req.message,
        )
        numbers_ok, _claims = check_numbers(
            cleaned.customer_reply, matches=prompt_matches, deal=deal,
            customer_message=req.message,
        )
        lang_ok = check_language(cleaned.customer_reply, lang)
        script_problems = check_output_script(cleaned)
        role_problems = check_manager_referral(cleaned.customer_reply)
        leaks = check_leakage(
            cleaned, candidates, message=req.message, matches=matches,
            threshold=threshold, deal_plan=deal.plan,
        )
        length_ok = check_length(cleaned.customer_reply)
        capacity_problems = check_plan_capacity(cleaned.customer_reply, req.message)

        problems = list(candidate_problems)
        if not lang_ok:
            problems.append(f"language_ok failed: reply is not {lang}")
        if not numbers_ok:
            bad = find_bad_claim(
                cleaned.customer_reply,
                matches=prompt_matches,
                deal=deal,
                customer_message=req.message,
            )
            detail = f" [unsupported claim: {bad.raw!r} unit={bad.unit}]" if bad else ""
            problems.append(
                "numbers_ok failed: quote numbers exactly as they appear in <kb> — "
                "never repeat the customer's discount percentages, never compute "
                "totals, and always attach a unit (%, ₽, users, days, hours)" + detail
            )
        problems += capacity_problems
        problems += script_problems
        problems += role_problems
        problems += leaks
        if not length_ok:
            problems.append("length_ok failed: reply empty or over 450 chars")

        validation = Validation(
            schema_ok=True,
            candidates_ok=not candidate_problems,
            language_ok=lang_ok,
            numbers_ok=numbers_ok,
            capacity_ok=not capacity_problems,
            script_ok=not script_problems,
            role_ok=not role_problems,
            no_leakage=not leaks,
            length_ok=length_ok,
            errors=problems,
        )
        validate_ms += int((time.monotonic() - t0) * 1000)
        if not problems:
            final_output = cleaned
            break
        attempt_errors = problems
        prev_reply = cleaned.customer_reply
        logger.warning(
            "assist validation failed attempt=%d message=%r problems=%s reply=%r",
            attempt, req.message[:80], problems[:6], cleaned.customer_reply[:160],
        )

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
                latency_ms=elapsed(), retrieve_ms=retrieve_ms, prompt_ms=prompt_ms,
                llm_ms=llm_ms, validate_ms=validate_ms,
            ),
        )

    # LLM unavailable or invalid twice: templated reply + templated reasons (§18).
    # The template path keeps the LAST attempt's flags (schema parsed fine but
    # script/role/numbers failed), so the UI and harness see what was wrong.
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
            latency_ms=elapsed(), retrieve_ms=retrieve_ms, prompt_ms=prompt_ms,
            llm_ms=llm_ms, validate_ms=validate_ms,
        ),
    )


# Serve the built frontend (npm --prefix frontend run build → frontend/dist),
# so one uvicorn/docker process hosts the whole app. Mounted last so it never
# shadows the /api routes above.
_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_DIST_DIR, html=True), name="frontend")
