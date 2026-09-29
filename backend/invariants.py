"""Response invariants for the MCP harness (run 20260929-175559, STEP 6).

Checks that run on EVERY case, independent of each case's expectations, so a
green run means the pipeline itself never emits:

- text outside the allowed script (the ru31/x13 Chinese replies);
- template/meta artifacts in any output field;
- a reply that routes the customer to "the manager" (the reply IS the
  manager's message);
- replies over the 450-character limit;
- plan/add-on titles the customer never asked about and that were not
  retrieved sources (ru01/ru22/ru18 upsell pitches).

Scope decision, documented once: the plan-title check is skipped for
fallback replies (`validation.fallback_used`). Templates are deterministic
code built from KB facts — the pricing fallback legitimately names every
plan and cannot leak internal text — while the rule exists to catch MODEL
regressions. All other invariants run on every reply, template or not.
"""

from typing import Any

from backend.kb import get_kb
from backend.retriever import Match
from backend.validators import (
    check_length,
    check_manager_referral,
    check_meta_markers,
    check_script,
    unallowed_plan_mentions,
)

INVARIANT_NAMES = (
    "invariant: script whitelist",
    "invariant: no meta markers",
    "invariant: no manager referral",
    "invariant: reply <= 450 chars",
    "invariant: no unallowed plan/add-on title in reply",
)


def _hint_texts(assist: dict[str, Any]) -> list[str]:
    hints = assist.get("internal_sales_hints") or {}
    texts: list[str] = []
    for kind in ("upsell", "cross_sell"):
        for item in hints.get(kind) or []:
            texts.append(item.get("reason", ""))
            texts.append(item.get("talking_point", ""))
    if hints.get("notes"):
        texts.append(hints["notes"])
    return texts


def _rebuild_matches(retrieve: dict[str, Any]) -> list[Match]:
    entries = {e.id: e for e in get_kb()}
    rebuilt: list[Match] = []
    for m in retrieve.get("matches") or []:
        entry = entries.get(m.get("id"))
        if entry is not None:
            rebuilt.append(
                Match(entry=entry, score=float(m.get("score", 0.0)),
                      matched_terms=list(m.get("matched_terms") or []))
            )
    return rebuilt


def evaluate_invariants(
    case: dict[str, Any], retrieve: dict[str, Any], assist: dict[str, Any]
) -> list[dict[str, Any]]:
    """Five checks, always in the same order; each result uses the harness
    check shape {name, ok, expected, actual}."""
    reply = assist["customer_reply"]["text"]
    texts = [reply, *_hint_texts(assist)]
    fallback = bool((assist.get("validation") or {}).get("fallback_used"))
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, actual: object) -> None:
        checks.append({"name": name, "ok": bool(ok), "expected": True, "actual": actual})

    script_problem = next((p for t in texts for p in check_script(t)), None)
    add(INVARIANT_NAMES[0], script_problem is None, script_problem)

    meta_problem = next((p for t in texts for p in check_meta_markers(t)), None)
    add(INVARIANT_NAMES[1], meta_problem is None, meta_problem)

    referral_problem = next(iter(check_manager_referral(reply)), None)
    add(INVARIANT_NAMES[2], referral_problem is None, referral_problem)

    add(INVARIANT_NAMES[3], check_length(reply), len(reply))

    if fallback:
        title_problems: list[str] = []
    else:
        title_problems = unallowed_plan_mentions(
            reply,
            message=case.get("message", ""),
            matches=_rebuild_matches(retrieve),
            threshold=float(retrieve.get("threshold", 0.0)),
            deal_plan=(case.get("deal") or {}).get("plan"),
        )
    add(INVARIANT_NAMES[4], not title_problems, title_problems or None)

    return checks
