"""Pricing intent without a product (Task A): a TEMPLATED reply built only
from plan KB facts, no LLM. Regression tests fail before the fix because
pricing_fallback_reply does not exist yet and /api/assist returns the generic
"I'll check with the team" template for ungrounded pricing questions.
"""

import pytest

from backend.fallback import pricing_fallback_reply
from backend.kb import get_kb
from backend.models import DealContext
from backend.retriever import Match, get_retriever
from backend.validators import check_numbers, check_script


def plan_matches() -> list[Match]:
    return [
        Match(entry=e, score=0.0, matched_terms=[])
        for e in get_kb()
        if e.type == "plan"
    ]


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_pricing_template_is_grounded_in_kb_and_passes_guardrail(lang) -> None:
    text = pricing_fallback_reply(lang)
    assert text
    # every number comes from plan facts and passes the numeric guardrail
    numbers_ok, claims = check_numbers(
        text, matches=plan_matches(), deal=DealContext(), customer_message="Сколько стоит?"
    )
    assert numbers_ok, [c.raw for c in claims]
    # script whitelist: the template must be clean by construction
    assert check_script(text) == []
    # names the plans and the prices from KB facts
    assert "990" in text
    assert "1 990" in text or "1,990" in text
    # asks which plan the customer means
    assert "?" in text


def test_ungrounded_pricing_returns_template_without_llm(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.app import app

    client = TestClient(app)

    def boom(messages):
        raise AssertionError("LLM must not be called for an ungrounded pricing ask")

    monkeypatch.setattr("backend.app.generate", boom)
    matches, _threshold, grounded = get_retriever().retrieve("Сколько стоит?")
    assert grounded is False  # precondition: this question has no KB match

    response = client.post(
        "/api/assist", json={"message": "Сколько стоит?", "ui_lang": "ru", "deal": {}}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "pricing"
    assert data["grounded"] is False
    assert data["validation"]["fallback_used"] is True
    text = data["customer_reply"]["text"]
    assert "990" in text and "1 990" in text
    assert data["internal_sales_hints"]["upsell"] == []
    assert data["internal_sales_hints"]["cross_sell"] == []


def test_ungrounded_en_pricing_returns_template(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.app import app

    client = TestClient(app)

    def boom(messages):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr("backend.app.generate", boom)
    response = client.post(
        "/api/assist", json={"message": "Price?", "ui_lang": "en", "deal": {}}
    )
    data = response.json()
    assert data["intent"] == "pricing"
    assert data["grounded"] is False
    text = data["customer_reply"]["text"]
    assert "990" in text
    assert data["customer_reply"]["lang"] == "en"


def test_ungrounded_non_pricing_keeps_generic_template(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.app import app

    client = TestClient(app)

    monkeypatch.setattr(
        "backend.app.generate",
        lambda messages: pytest.fail("LLM must not be called"),
    )
    response = client.post(
        "/api/assist",
        json={"message": "Сможете сделать кастомное мобильное приложение?", "ui_lang": "ru",
              "deal": {}},
    )
    data = response.json()
    assert data["intent"] != "pricing"
    assert "уточню детали у команды" in data["customer_reply"]["text"]
    assert "990" not in data["customer_reply"]["text"]


def test_grounded_pricing_still_uses_llm(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.app import app
    from tests.test_api_assist import make_generate

    client = TestClient(app)
    monkeypatch.setattr(
        "backend.app.generate",
        make_generate("Тариф «Старт» стоит 990 ₽ за пользователя в месяц."),
    )
    matches, _threshold, grounded = get_retriever().retrieve(
        "Сколько стоят тарифы у вас?"
    )
    assert grounded is True  # precondition: the plural pricing question matches KB

    response = client.post(
        "/api/assist", json={"message": "Сколько стоят тарифы у вас?", "ui_lang": "ru",
                             "deal": {}}
    )
    data = response.json()
    assert data["validation"]["fallback_used"] is False
    assert data["customer_reply"]["text"].startswith("Тариф «Старт»")
