from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_retrieve_russian_happy_path() -> None:
    resp = client.post(
        "/api/retrieve",
        json={
            "message": "Сколько пользователей можно подключить на тарифе Старт?",
            "ui_lang": "ru",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detected_lang"] == "ru"
    assert data["lang_source"] == "message"
    assert data["grounded"] is True
    ids = [m["id"] for m in data["matches"]]
    assert ids[0] == "plan-start"
    assert data["threshold"] > 0
    assert all("score" in m and "matched_terms" in m for m in data["matches"])


def test_retrieve_detects_english() -> None:
    resp = client.post(
        "/api/retrieve",
        json={"message": "Do you have a Telegram integration?", "ui_lang": "ru"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detected_lang"] == "en"
    assert data["grounded"] is True


def test_retrieve_out_of_scope_is_ungrounded() -> None:
    resp = client.post(
        "/api/retrieve",
        json={"message": "Сможете сделать для нас кастомное мобильное приложение под iOS?"},
    )
    assert resp.status_code == 200
    assert resp.json()["grounded"] is False


def test_retrieve_title_localised_to_ui_lang() -> None:
    resp = client.post(
        "/api/retrieve",
        json={
            "message": "Сколько пользователей на тарифе Старт?",
            "ui_lang": "en",
        },
    )
    assert resp.status_code == 200
    plan = next(m for m in resp.json()["matches"] if m["id"] == "plan-start")
    assert plan["title"] == "Start plan"


def test_retrieve_short_message_inherits_conversation_language() -> None:
    resp = client.post(
        "/api/retrieve",
        json={
            "message": "Price?",
            "ui_lang": "ru",
            "history": [{"role": "customer", "text": "Здравствуйте, мы на тарифе Старт."}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detected_lang"] == "ru"
    assert data["lang_source"] == "conversation"


def test_retrieve_rejects_empty_message() -> None:
    resp = client.post("/api/retrieve", json={"message": ""})
    assert resp.status_code == 422


def test_assist_shares_the_retriever_with_retrieve(monkeypatch) -> None:
    """Contract (CONTEXT §4a): /api/assist must call the SAME retrieval service
    as /api/retrieve — identical matches, threshold and grounded for one message."""

    def generate(messages):
        return (
            {
                "customer_reply": "Здравствуйте! На тарифе «Старт» до 5 пользователей.",
                "upsell_reasons": [],
                "cross_sell_reasons": [],
            },
            "qwen2.5:7b",
        )

    monkeypatch.setattr("backend.app.generate", generate)
    message = "Сколько пользователей можно подключить на тарифе Старт?"

    retrieved = client.post("/api/retrieve", json={"message": message, "ui_lang": "ru"})
    assisted = client.post(
        "/api/assist",
        json={"message": message, "ui_lang": "ru", "history": [], "deal": {}},
    )
    assert retrieved.status_code == 200 and assisted.status_code == 200

    r, a = retrieved.json(), assisted.json()
    assert a["retrieval"]["threshold"] == r["threshold"]
    assert a["retrieval"]["matches"] == r["matches"]
    assert a["grounded"] == r["grounded"]
    assert a["detected_lang"] == r["detected_lang"]

    from backend.retriever import get_retriever as original

    calls = {"n": 0}

    def spy():
        calls["n"] += 1
        return original()

    import backend.app as app_module

    monkeypatch.setattr(app_module, "get_retriever", spy)
    client.post("/api/retrieve", json={"message": message, "ui_lang": "ru"})
    client.post(
        "/api/assist",
        json={"message": message, "ui_lang": "ru", "history": [], "deal": {}},
    )
    assert calls["n"] == 2
