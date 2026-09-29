"""Deterministic rule engine: intent detection + upsell/cross-sell candidates (CONTEXT §15).

The engine — not the LLM — decides *which* recommendations are candidates.
The LLM only phrases reasons for ids the engine produced.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from backend.models import DealContext
from backend.retriever import Match, tokenize

# Intent priority: first intent with a matching phrase wins (§15 keyword rules).
# Objection outranks pricing so "дороговато … есть скидки?" is an objection
# (drives the onboarding cross-sell), not a plain pricing question.
INTENT_ORDER = ["objection", "reporting", "support", "pricing", "limits", "integration", "other"]

_INTENT_PHRASES: dict[str, list[str]] = {
    "objection": [
        "дорого",
        "дороговато",
        "дорогая",
        "подумать",
        "сравнить",
        "конкурент",
        "конкуренты",
        "сомневаюсь",
        "не нравится",
        "много",
        "expensive",
        "think about",
        "competitor",
        "too much",
    ],
    "reporting": [
        "отчёт",
        "отчёты",
        "отчет",
        "аналитика",
        "аналитику",
        "конверсия",
        "воронка",
        "report",
        "reports",
        "analytics",
        "conversion",
        "funnel",
    ],
    "support": [
        "поддержка",
        "поддержки",
        "срочно",
        "быстро",
        "скорость",
        "sla",
        "priority",
        "urgent",
        "fast",
        "support",
        "response time",
    ],
    "pricing": [
        "цена",
        "цены",
        "стоимость",
        "стоит",
        "стоить",
        "дешево",
        "скидка",
        "скидки",
        "скидку",
        "бюджет",
        "оплата",
        "оплатить",
        "price",
        "cost",
        "discount",
        "budget",
        "billing",
        "invoice",
        "pay",
    ],
    "limits": [
        "лимит",
        "пользователи",
        "пользователей",
        "сотрудники",
        "сотрудников",
        "места",
        "максимум",
        "предел",
        "limit",
        "users",
        "seats",
        "employees",
        "how many",
        "maximum",
    ],
    "integration": [
        "интеграция",
        "интеграции",
        "подключить",
        "connect",
        "integration",
        "telegram",
        "whatsapp",
        "1c",
        "google",
        "api",
        "rest",
    ],
}


def _phrase_stems(phrase: str) -> frozenset[str]:
    return frozenset(tokenize(phrase))


_INTENT_STEMS: dict[str, list[frozenset[str]]] = {
    intent: [stems for stems in (_phrase_stems(p) for p in phrases) if stems]
    for intent, phrases in _INTENT_PHRASES.items()
}


def detect_intent(message: str) -> str:
    """Keyword intent over the stemmed message (the LLM is not used for intent)."""
    tokens = set(tokenize(message))
    if not tokens:
        return "other"
    for intent in INTENT_ORDER:
        for stems in _INTENT_STEMS.get(intent, []):
            if stems <= tokens:
                return intent
    return "other"


PLAN_ORDER = {"none": -1, "start": 0, "business": 1, "enterprise": 2}
NEXT_PLAN = {"start": "plan-business", "business": "plan-enterprise"}
MAX_UPSELL = 1
MAX_CROSS_SELL = 2

ENTITLEMENT_RULES = {
    "seats_near_limit",
    "feature_needs_higher_plan",
    "reporting_interest",
    "support_interest",
    "price_objection_onboarding",
    "enterprise_scale",
}


@dataclass(frozen=True)
class Candidate:
    id: str
    rule: str


@dataclass(frozen=True)
class Candidates:
    upsell: list[Candidate] = field(default_factory=list)
    cross_sell: list[Candidate] = field(default_factory=list)


def _plan_rank(plan_ref: str) -> int:
    """Rank of "business" or "plan-business" in the tier ladder."""
    return PLAN_ORDER.get(plan_ref.removeprefix("plan-"), -1)


def find_candidates(
    matches: Sequence[Match],
    intent: str,
    deal: DealContext,
    message: str,
) -> Candidates:
    """Deterministic upsell/cross-sell candidates from §15 triggers.

    Returns ids only (with the rule that fired) — the LLM phrases the reasons.
    """
    upsell: list[Candidate] = []
    cross: list[Candidate] = []

    def add(bucket: list[Candidate], candidate_id: str, rule: str) -> None:
        if not any(c.id == candidate_id for c in bucket):
            bucket.append(Candidate(id=candidate_id, rule=rule))

    # enterprise_scale first: an explicit "60 users" / "SSO" ask outranks
    # the seat-based next-plan suggestion when both fire (cap = 1 upsell).
    numbers = [int(n) for n in re.findall(r"\d+", message)]
    tokens = set(tokenize(message))
    if deal.plan != "enterprise" and (any(n > 50 for n in numbers) or "sso" in tokens):
        add(upsell, "plan-enterprise", "enterprise_scale")

    # seats_near_limit: seats_used / seat_limit ≥ 0.9 and a higher tier exists
    if deal.seat_limit > 0 and deal.seats_used / deal.seat_limit >= 0.9:
        next_plan = NEXT_PLAN.get(deal.plan)
        if next_plan:
            add(upsell, next_plan, "seats_near_limit")

    # feature_needs_higher_plan: top match requires a plan above the current one
    if matches:
        required = matches[0].entry.requires
        if required and _plan_rank(deal.plan) < _plan_rank(required):
            add(upsell, required, "feature_needs_higher_plan")

    # reporting_interest: reports/analytics intent, plan ≥ Business, not owned
    if (
        intent == "reporting"
        and _plan_rank(deal.plan) >= _plan_rank("plan-business")
        and "addon-analytics" not in deal.addons_owned
    ):
        add(cross, "addon-analytics", "reporting_interest")

    # support_interest: SLA/urgent intent, not owned
    if intent == "support" and "addon-priority-support" not in deal.addons_owned:
        add(cross, "addon-priority-support", "support_interest")

    # price_objection_onboarding: objection during trial/negotiation.
    # Phrasing guard (§15): onboarding is framed as cutting self-setup time,
    # offered after the tariff discussion — never "expensive → buy more".
    if intent == "objection" and deal.stage in {"trial", "negotiation"}:
        add(cross, "addon-onboarding", "price_objection_onboarding")

    # Never upsell the plan the deal already has.
    upsell = [c for c in upsell if _plan_rank(c.id) > _plan_rank(deal.plan)]

    return Candidates(upsell=upsell[:MAX_UPSELL], cross_sell=cross[:MAX_CROSS_SELL])
