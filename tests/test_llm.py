import json

import httpx
import pytest

from backend import llm
from backend.llm import LlmUnavailable, LlmUnparsable, build_payload, generate

MESSAGES = [{"role": "user", "content": "hi"}]


def _response(payload: dict) -> httpx.Response:
    request = httpx.Request("POST", "http://localhost/api/chat")
    return httpx.Response(200, json=payload, request=request)


def test_build_payload_matches_spec() -> None:
    payload = build_payload(MESSAGES, "qwen2.5:7b")
    assert payload["model"] == "qwen2.5:7b"
    assert payload["stream"] is False
    assert payload["keep_alive"] == "30m"
    assert payload["options"] == {"temperature": 0.2, "seed": 42, "num_ctx": 4096}
    assert payload["format"] is llm.OUTPUT_SCHEMA
    assert payload["format"]["required"] == [
        "customer_reply",
        "upsell_reasons",
        "cross_sell_reasons",
    ]


def test_generate_returns_parsed_output(monkeypatch) -> None:
    body = {
        "message": {
            "content": json.dumps(
                {
                    "customer_reply": "Здравствуйте!",
                    "upsell_reasons": [],
                    "cross_sell_reasons": [],
                }
            )
        }
    }
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _response(body))
    output, model = generate(MESSAGES)
    assert output["customer_reply"] == "Здравствуйте!"
    assert model == llm.PRIMARY_MODEL


def test_generate_falls_back_to_smaller_model(monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(url, json=None, timeout=None):  # noqa: A002
        calls.append(json["model"])
        if json["model"] == llm.PRIMARY_MODEL:
            raise httpx.ReadTimeout("timeout")
        return _response(
            {"message": {"content": '{"customer_reply": "ok", "upsell_reasons": [], "cross_sell_reasons": []}'}}
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    _, model = generate(MESSAGES)
    assert calls == [llm.PRIMARY_MODEL, llm.FALLBACK_MODEL]
    assert model == llm.FALLBACK_MODEL


def test_generate_raises_when_all_models_fail(monkeypatch) -> None:
    def fake_post(url, json=None, timeout=None):  # noqa: A002
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    with pytest.raises(LlmUnavailable):
        generate(MESSAGES)


def test_unparsable_output_raises() -> None:
    with pytest.raises(LlmUnparsable):
        llm._parse("not json at all")


def test_empty_response_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        llm.httpx, "post", lambda *a, **k: _response({"message": {"content": ""}})
    )
    with pytest.raises(LlmUnavailable):
        generate(MESSAGES)
