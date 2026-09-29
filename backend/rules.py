"""Deterministic rule engine: intent detection + upsell/cross-sell candidates (CONTEXT §15).

The engine — not the LLM — decides *which* recommendations are candidates.
The LLM only phrases reasons for ids the engine produced.
"""

from backend.retriever import tokenize

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
