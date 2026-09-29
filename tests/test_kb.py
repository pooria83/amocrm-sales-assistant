import json

import pytest

from backend.kb import KbEntry, KbError, load_kb


def test_kb_loads_and_contains_plan_entries() -> None:
    entries = load_kb()
    ids = [e.id for e in entries]
    for expected in ["plan-start", "plan-business", "plan-enterprise", "limit-seats"]:
        assert expected in ids
    start = next(e for e in entries if e.id == "plan-start")
    assert start.facts["max_users"] == 5
    assert start.upsell_to == ["plan-business"]


def test_integrations_and_addons_entries() -> None:
    entries = load_kb()
    by_id = {e.id: e for e in entries}
    for expected in [
        "int-telegram",
        "int-whatsapp",
        "int-1c",
        "int-gsheets",
        "faq-api",
        "addon-analytics",
        "addon-priority-support",
        "addon-onboarding",
        "security-data",
    ]:
        assert expected in by_id, expected
    assert by_id["int-1c"].requires == "plan-business"
    assert by_id["int-telegram"].requires is None
    assert by_id["addon-analytics"].facts["price_rub_per_month"] == 4900
    assert by_id["addon-onboarding"].facts["price_rub_one_time"] == 29900
    assert by_id["addon-priority-support"].facts["response_hours"] == 1


def test_duplicate_ids_rejected(tmp_path) -> None:
    entry = {
        "id": "plan-start",
        "type": "plan",
        "title": {"ru": "Старт", "en": "Start"},
        "text": {"ru": "Текст", "en": "Text"},
        "keywords": {"ru": ["тариф"], "en": ["plan"]},
        "facts": {},
    }
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"entries": [entry, entry]}), encoding="utf-8")
    with pytest.raises(KbError, match="duplicate"):
        load_kb(path)


def test_unknown_relation_target_rejected(tmp_path) -> None:
    entry = {
        "id": "plan-start",
        "type": "plan",
        "title": {"ru": "Старт", "en": "Start"},
        "text": {"ru": "Текст", "en": "Text"},
        "keywords": {"ru": ["тариф"], "en": ["plan"]},
        "facts": {},
        "upsell_to": ["plan-missing"],
    }
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    with pytest.raises(KbError, match="unknown relation target"):
        load_kb(path)


def test_fact_key_without_unit_rejected(tmp_path) -> None:
    entry = {
        "id": "billing",
        "type": "faq",
        "title": {"ru": "Оплата", "en": "Billing"},
        "text": {"ru": "Текст", "en": "Text"},
        "keywords": {"ru": ["скидка"], "en": ["discount"]},
        "facts": {"value": 20},
    }
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    with pytest.raises(KbError):
        load_kb(path)


def test_entry_requires_both_languages(tmp_path) -> None:
    entry = {
        "id": "billing",
        "type": "faq",
        "title": {"ru": "Оплата"},
        "text": {"ru": "Текст", "en": "Text"},
        "keywords": {"ru": ["скидка"], "en": ["discount"]},
        "facts": {},
    }
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    with pytest.raises(KbError):
        load_kb(path)


def test_kb_entry_unit_rule_in_model() -> None:
    with pytest.raises(ValueError):
        KbEntry.model_validate(
            {
                "id": "x",
                "type": "faq",
                "title": {"ru": "а", "en": "b"},
                "text": {"ru": "а", "en": "b"},
                "keywords": {"ru": ["а"], "en": ["b"]},
                "facts": {"discount": 20},
            }
        )
