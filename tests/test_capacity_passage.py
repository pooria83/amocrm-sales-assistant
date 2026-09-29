"""Capacity mismatch → the fitting plan is added to the prompt (Task B).

Regression: "тарфи для 10 сотрудников" used to fail twice into the fallback
because only plan-start (990 ₽, max 5) was in the passages. The fix appends
plans whose max_users >= N to the KB passages given to the LLM — without
touching kb_refs (still retrieval-only) and without weakening the capacity
guardrail.
"""

from backend.kb import get_kb

RU21_MSG = "тарфи для 10 сотрудников"
BUSINESS_ANSWER = (
    "Для 10 сотрудников нужен тариф с большим лимитом: до 50 пользователей, "
    "1 990 ₽ за пользователя в месяц."
)


def test_prompt_gets_fitting_plan_passage(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.app import app
    from tests.test_api_assist import make_generate

    client = TestClient(app)
    captured = []
    inner = make_generate(BUSINESS_ANSWER)([])

    def generate(messages):
        captured.append(messages)
        return inner

    monkeypatch.setattr("backend.app.generate", generate)
    response = client.post("/api/assist", json={"message": RU21_MSG, "ui_lang": "ru", "deal": {}})
    assert response.status_code == 200
    data = response.json()

    # the LLM was called at all (this used to end in a double failure)
    assert captured, "expected an LLM call"
    prompt = captured[0][1]["content"]
    assert "plan-business" in prompt  # fitting plan appended to <kb>
    assert "1990" in prompt or "1 990" in prompt

    # kb_refs still reflect retrieval only — plan-business was NOT retrieved
    assert "plan-business" not in data["customer_reply"]["kb_refs"]
    shown = [m["id"] for m in data["retrieval"]["matches"]]
    assert "plan-business" not in shown

    # guardrail intact: numbers pass with the appended plan facts ...
    assert data["validation"]["fallback_used"] is False
    assert data["validation"]["numbers_ok"] is True
    assert data["validation"]["capacity_ok"] is True
    assert "1 990" in data["customer_reply"]["text"]
    # ... and the under-sized Start plan is never presented as the answer
    assert "Старт" not in data["customer_reply"]["text"]


def test_capacity_fit_plan_pitch_is_title_blocked(monkeypatch) -> None:
    """STEP 4 still applies: an upgrade pitch for the un-retrieved fit plan
    must not be used. (A bare factual mention of the fit plan is allowed —
    the capacity passage exists so the model may name it.)"""
    from fastapi.testclient import TestClient

    from backend.app import app
    from tests.test_api_assist import make_generate

    client = TestClient(app)
    outputs = [
        make_generate(
            "Если нужен больший лимит, рассмотрите тариф «Бизнес»: "
            "до 50 пользователей, 1 990 ₽ в месяц."
        )([]),
        make_generate(BUSINESS_ANSWER)([]),
    ]
    monkeypatch.setattr("backend.app.generate", lambda messages: outputs.pop(0))

    response = client.post("/api/assist", json={"message": RU21_MSG, "ui_lang": "ru", "deal": {}})
    data = response.json()

    assert data["validation"]["retries"] == 1
    assert data["validation"]["fallback_used"] is False
    assert "Бизнес" not in data["customer_reply"]["text"]


def test_no_capacity_mismatch_no_extra_passage(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from backend.app import app
    from tests.test_api_assist import make_generate

    client = TestClient(app)
    captured = []
    inner = make_generate("На тарифе «Старт» до 5 пользователей.")([])

    def generate(messages):
        captured.append(messages)
        return inner

    monkeypatch.setattr("backend.app.generate", generate)
    client.post(
        "/api/assist",
        json={"message": "Сколько пользователей на тарифе Старт?", "ui_lang": "ru",
              "deal": {}},
    )
    prompt = captured[0][1]["content"]
    kb_block = prompt.split("</kb>")[0]
    # only the retrieved passages, no appended plans
    assert kb_block.count("plan-") <= 4  # ids appear as [id] markers


def test_fitting_plan_definition() -> None:
    from backend.validators import inapplicable_plans

    capacity, bad = inapplicable_plans(RU21_MSG)
    assert capacity == 10
    assert {e.id for e in bad} == {"plan-start"}  # business (50) and enterprise fit
    fitting = [
        e for e in get_kb()
        if e.type == "plan"
        and e.id not in {x.id for x in bad}
        and isinstance(e.facts.get("max_users"), int | float)
        and e.facts["max_users"] >= capacity
    ]
    assert {e.id for e in fitting} == {"plan-business"}
