"""Plan-capacity guardrail: a plan under the customer's user count must not be
presented as suitable (regression for run 20260929-155851, ru21_typo_tarfy —
a reply recommending «Бизнес» for 10 employees while quoting Start's 990 ₽).
"""

from fastapi.testclient import TestClient

from backend.app import app
from backend.models import DealContext
from backend.retriever import get_retriever
from backend.validators import (
    allowed_numbers,
    check_numbers,
    check_plan_capacity,
    inapplicable_plans,
    requested_capacity,
)

client = TestClient(app)

MSG_RU10 = "тарфи для 10 сотрудников"
MSG_EN10 = "Which plan for 10 users?"


def deal(**overrides) -> DealContext:
    base = dict(contact="Тест", plan="start", seats_used=5, seat_limit=5, stage="client")
    base.update(overrides)
    return DealContext(**base)


# ---------------------------------------------------------------------------
# requested_capacity / inapplicable_plans
# ---------------------------------------------------------------------------


def test_requested_capacity_ru_and_en() -> None:
    assert requested_capacity(MSG_RU10) == 10
    assert requested_capacity(MSG_EN10) == 10
    assert requested_capacity("Мы команда в 6 человек") == 6


def test_requested_capacity_none_without_user_claim() -> None:
    assert requested_capacity("Сколько стоит тариф Старт?") is None
    assert requested_capacity("Do you support SSO?") is None
    assert requested_capacity("Скидка 10% нам нужна") is None  # percent, not users


def test_inapplicable_plans_boundaries() -> None:
    capacity, entries = inapplicable_plans(MSG_RU10)
    assert capacity == 10
    assert [e.id for e in entries] == ["plan-start"]  # max_users=5 < 10

    _, at_five = inapplicable_plans("тариф на 5 сотрудников")
    assert at_five == []  # Start fits exactly 5

    _, at_six = inapplicable_plans("тариф на 6 сотрудников")
    assert [e.id for e in at_six] == ["plan-start"]

    _, at_sixty = inapplicable_plans("для 60 сотрудников")
    assert [e.id for e in at_sixty] == ["plan-start", "plan-business"]
    # Enterprise has no max_users ("50+") and must never be blocked:
    assert all(e.id != "plan-enterprise" for e in at_sixty)


def test_inapplicable_plans_no_constraint_without_claim() -> None:
    assert inapplicable_plans("Сколько стоит тариф Старт?") == (None, [])


# ---------------------------------------------------------------------------
# numeric side: the inapplicable plan's facts leave the allowlist
# ---------------------------------------------------------------------------


def test_inapplicable_plan_price_rejected() -> None:
    matches = get_retriever().search(MSG_RU10)
    assert any(m.entry.id == "plan-start" for m in matches)  # premise
    allowed = allowed_numbers(matches, deal(), MSG_RU10)
    assert 990.0 not in allowed["rub"]

    ok, _ = check_numbers(
        "Тариф «Бизнес» для 10 человек, 990 ₽ в месяц.",
        matches=matches,
        deal=deal(),
        customer_message=MSG_RU10,
    )
    assert ok is False


def test_same_reply_passes_when_capacity_fits() -> None:
    msg = "тариф на 5 сотрудников"
    matches = get_retriever().search(msg)
    allowed = allowed_numbers(matches, deal(), msg)
    assert 990.0 in allowed["rub"]  # Start applies at 5 users
    ok, _ = check_numbers(
        "Тариф «Старт» — 990 ₽ за пользователя в месяц.",
        matches=matches,
        deal=deal(),
        customer_message=msg,
    )
    assert ok is True


# ---------------------------------------------------------------------------
# check_plan_capacity: naming an under-sized plan as the answer
# ---------------------------------------------------------------------------


def test_capacity_rejects_presenting_start_for_ten() -> None:
    problems = check_plan_capacity(
        "Здравствуйте! Тариф «Старт» подойдёт для 10 сотрудников, 990 ₽ в месяц.",
        MSG_RU10,
    )
    assert problems
    assert "plan_capacity_ok" in problems[0]


def test_capacity_allows_business_for_ten() -> None:
    assert check_plan_capacity(
        "Здравствуйте! Для 10 сотрудников подойдёт тариф «Бизнес», 1990 ₽ в месяц.",
        MSG_RU10,
    ) == []


def test_capacity_allows_explaining_the_limit() -> None:
    reply = (
        "Здравствуйте! Тариф «Старт» не подойдёт — максимум 5 пользователей. "
        "Для 10 человек рекомендуем «Бизнес»."
    )
    assert check_plan_capacity(reply, MSG_RU10) == []


def test_capacity_no_constraint_when_message_has_no_claim() -> None:
    msg = "Сколько стоит тариф Старт?"
    assert check_plan_capacity("Тариф «Старт» стоит 990 ₽ в месяц.", msg) == []


def test_capacity_ignores_replies_that_never_name_a_plan() -> None:
    # "get started" contains the stem "start" but is not a plan reference.
    assert check_plan_capacity("We can get started right away.", MSG_EN10) == []


def test_capacity_en_rejects_start_for_ten() -> None:
    reply = "Hello! The Start plan works for your team, 990 RUB per user per month."
    problems = check_plan_capacity(reply, MSG_EN10)
    assert problems and "plan_capacity_ok" in problems[0]


def test_capacity_en_allows_business_for_ten() -> None:
    reply = "Hello! The Business plan fits 10 users, 1,990 RUB per user per month."
    assert check_plan_capacity(reply, MSG_EN10) == []


# ---------------------------------------------------------------------------
# API level: retry then succeed / retry then honest fallback
# ---------------------------------------------------------------------------

BAD_CAPACITY_REPLY = "Здравствуйте! Тариф «Старт» подойдёт для 10 сотрудников, 990 ₽ в месяц."
FIXED_CAPACITY_REPLY = "Здравствуйте! Для 10 сотрудников нужен другой тариф — уточню условия."


def _generate_sequence(outputs):
    calls = []

    def generate(messages):
        calls.append(messages)
        return outputs[len(calls) - 1], "qwen2.5:7b"

    return generate, calls


def _post(message: str) -> dict:
    response = client.post(
        "/api/assist",
        json={"message": message, "ui_lang": "ru", "history": [], "deal": {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_api_capacity_bad_reply_retried_then_fixed(monkeypatch) -> None:
    bad = {
        "customer_reply": BAD_CAPACITY_REPLY,
        "upsell_reasons": [],
        "cross_sell_reasons": [],
    }
    good = {
        "customer_reply": FIXED_CAPACITY_REPLY,
        "upsell_reasons": [],
        "cross_sell_reasons": [],
    }
    generate, calls = _generate_sequence([bad, good])
    monkeypatch.setattr("backend.app.generate", generate)

    data = _post(MSG_RU10)

    assert len(calls) == 2  # one retry
    assert data["validation"]["retries"] == 1
    assert data["validation"]["fallback_used"] is False
    assert data["validation"]["capacity_ok"] is True
    assert data["customer_reply"]["text"] == FIXED_CAPACITY_REPLY
    assert "990" not in data["customer_reply"]["text"]
    # the reminder sent on the retry names the failed check:
    reminder = calls[1][-1]["content"]
    assert "plan_capacity_ok failed" in reminder


def test_api_capacity_bad_twice_falls_back_without_bad_numbers(monkeypatch) -> None:
    bad = {
        "customer_reply": BAD_CAPACITY_REPLY,
        "upsell_reasons": [],
        "cross_sell_reasons": [],
    }
    generate, calls = _generate_sequence([bad, bad])
    monkeypatch.setattr("backend.app.generate", generate)

    data = _post(MSG_RU10)

    assert len(calls) == 2
    text = data["customer_reply"]["text"]
    assert data["validation"]["fallback_used"] is True
    assert data["validation"]["capacity_ok"] is False
    assert data["validation"]["numbers_ok"] is False  # pinned contract
    assert "990" not in text and "Старт" not in text  # never leaks into fallback
