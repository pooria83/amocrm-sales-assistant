"""Templated RU/EN fallback replies (CONTEXT §18) — no LLM involved.

Two situations:
- ungrounded (no KB match): honest "I'll check with the team" reply, no upsell;
- validation failed twice / LLM unavailable but grounded: safe confirmation
  template plus the rule-engine candidates with templated reasons, so the
  internal panel still works without the model.
"""


def _greeting(lang: str, contact: str) -> str:
    if lang == "ru":
        return f"Здравствуйте, {contact}!" if contact else "Здравствуйте!"
    return f"Hello {contact}," if contact else "Hello!"


def no_match_reply(customer_lang: str, contact: str = "") -> str:
    """Ungrounded path: honest template, never an invented answer (§18)."""
    if customer_lang == "ru":
        return (
            f"{_greeting('ru', contact)} Спасибо за вопрос. Чтобы не дать вам неточную "
            "информацию, я уточню детали у команды и вернусь с ответом."
        )
    return (
        f"{_greeting('en', contact)} Thank you for your question. To make sure I give you "
        "accurate information, I'll check the details with our team and get back to you."
    )


def no_match_note(ui_lang: str) -> str:
    """Internal note for the ungrounded path (manager's language)."""
    if ui_lang == "ru":
        return (
            "В базе знаний нет ответа. Передайте вопрос команде решений. "
            "Допродаж не предлагаем."
        )
    return "No KB answer. Escalate to the solutions team. No upsell suggested."


def validation_failed_reply(customer_lang: str, contact: str = "") -> str:
    """Grounded but unusable LLM output: safe confirmation template (§18)."""
    if customer_lang == "ru":
        return (
            f"{_greeting('ru', contact)} Спасибо за сообщение. Я уточняю детали "
            "и скоро отвечу."
        )
    return (
        f"{_greeting('en', contact)} Thank you for your message. I'm confirming "
        "the details and will reply shortly."
    )


def _rub(value: int, lang: str) -> str:
    """1990 → «1 990» (ru) / «1,990» (en) — same digits the KB stores."""
    text = f"{value:,}".replace(",", " ") if lang == "ru" else f"{value:,}"
    return text


def pricing_fallback_reply(lang: str, contact: str = "") -> str:
    """Ungrounded pricing question (Task A): facts-only plan list, no LLM.

    Built exclusively from plan KB facts (prices, seat limits), so the
    numeric guardrail passes by construction; check_numbers() in the tests
    proves it. Anything the KB does not price ("Enterprise") is explicitly
    deferred instead of guessed.
    """
    from backend.kb import get_kb  # local import: kb must not depend on fallback

    plans = {e.id: e for e in get_kb() if e.type == "plan"}
    start = plans["plan-start"].facts
    business = plans["plan-business"].facts
    if lang == "ru":
        return (
            f"{_greeting('ru', contact)} Тарифы TeamFlow: "
            f"«Старт» — {_rub(int(start['price_rub_per_user_month']), 'ru')} ₽ за "
            f"пользователя в месяц (до {start['max_users']} пользователей), "
            f"«Бизнес» — {_rub(int(business['price_rub_per_user_month']), 'ru')} ₽ за "
            f"пользователя в месяц (до {business['max_users']} пользователей), "
            "«Энтерпрайз» — цена рассчитывается индивидуально. "
            "Подскажите, какой тариф вам интересен?"
        )
    return (
        f"{_greeting('en', contact)} TeamFlow plans: "
        f"Start — {_rub(int(start['price_rub_per_user_month']), 'en')} RUB per user "
        f"per month (up to {start['max_users']} users), "
        f"Business — {_rub(int(business['price_rub_per_user_month']), 'en')} RUB per "
        f"user per month (up to {business['max_users']} users), "
        "Enterprise — priced on request. Which plan are you interested in?"
    )


# Templated reasons from rule names (§18) — used when the LLM could not
# phrase them. The onboarding wording follows the §15 phrasing guard:
# never "it's expensive → buy another paid thing".
_TEMPLATE_REASONS: dict[str, dict[str, tuple[str, str]]] = {
    "seats_near_limit": {
        "ru": (
            "Клиент подошёл к лимиту мест на текущем тарифе.",
            "Предложите перейти на тариф выше — там больше мест для сотрудников.",
        ),
        "en": (
            "The customer is close to the seat limit on the current plan.",
            "Offer the next tier — it includes more seats for the team.",
        ),
    },
    "feature_needs_higher_plan": {
        "ru": (
            "Запрошенная функция доступна на более высоком тарифе.",
            "Скажите, что нужная функция откроется на следующем тарифе.",
        ),
        "en": (
            "The requested feature requires a higher plan.",
            "Explain that the feature unlocks on the next plan.",
        ),
    },
    "reporting_interest": {
        "ru": (
            "Клиент спрашивает про отчёты и аналитику.",
            "Покажите расширенную аналитику: отчёты по менеджерам и конверсию воронки.",
        ),
        "en": (
            "The customer is asking about reports and analytics.",
            "Show Advanced Analytics: manager reports and funnel conversion.",
        ),
    },
    "support_interest": {
        "ru": (
            "Клиенту важна скорость ответа.",
            "Предложите приоритетную поддержку: первый ответ за 1 час в рабочие дни.",
        ),
        "en": (
            "Response speed matters to the customer.",
            "Offer Priority Support: a 1-hour first response on business days.",
        ),
    },
    "price_objection_onboarding": {
        "ru": (
            "Пакет внедрения помогает сократить время самостоятельной настройки "
            "и может быть предложен как дополнительная услуга после обсуждения тарифа.",
            "После обсуждения тарифа можно предложить помощь с настройкой "
            "и обучением команды.",
        ),
        "en": (
            "The onboarding package reduces self-setup time and can be offered "
            "after the plan discussion.",
            "After the plan discussion, offer setup help and team training.",
        ),
    },
    "enterprise_scale": {
        "ru": (
            "Клиент описывает масштаб выше лимитов текущего тарифа.",
            "Обсудите Enterprise: SSO, выделенный менеджер и SLA 99,9%.",
        ),
        "en": (
            "The customer describes a scale beyond the current plan.",
            "Discuss Enterprise: SSO, a dedicated manager and a 99.9% uptime SLA.",
        ),
    },
}


def templated_reason(rule: str, ui_lang: str) -> tuple[str, str]:
    """(reason, talking_point) for a rule name in the manager's language."""
    pairs = _TEMPLATE_REASONS.get(rule, {})
    reason, talking_point = pairs.get(ui_lang) or pairs.get("ru") or (
        "Допродажа подобрана по правилам.",
        "Уточните потребность клиента и предложите подходящий продукт.",
    )
    return reason, talking_point


def known_rules() -> frozenset[str]:
    return frozenset(_TEMPLATE_REASONS)
