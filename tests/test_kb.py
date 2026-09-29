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


SPEC_ENTRY_IDS = [
    "plan-start",
    "plan-business",
    "plan-enterprise",
    "limit-seats",
    "billing-cycles",
    "trial",
    "invoice-legal-entity",
    "cancel-policy",
    "refund-policy",
    "int-telegram",
    "int-whatsapp",
    "int-1c",
    "int-gsheets",
    "faq-api",
    "addon-analytics",
    "addon-priority-support",
    "addon-onboarding",
    "security-data",
    "obj-too-expensive",
    "obj-need-to-think",
    "obj-competitor-cheaper",
]


def test_complete_inventory_matches_spec() -> None:
    entries = load_kb()
    assert sorted(e.id for e in entries) == sorted(SPEC_ENTRY_IDS)


def test_spec_relations() -> None:
    by_id = {e.id: e for e in load_kb()}
    assert by_id["plan-business"].cross_sell == ["addon-analytics", "addon-onboarding"]
    assert by_id["plan-enterprise"].cross_sell == ["addon-priority-support"]
    assert by_id["obj-too-expensive"].cross_sell == ["addon-onboarding"]
    assert by_id["obj-too-expensive"].facts == {
        "discount_annual_percent": 20,
        "trial_days": 14,
    }
    assert by_id["billing-cycles"].facts == {"discount_annual_percent": 20}
    assert by_id["refund-policy"].facts == {"refund_days": 14}


def test_all_entries_bilingual_and_slug_ids() -> None:
    for entry in load_kb():
        assert entry.title.ru and entry.title.en
        assert entry.text.ru and entry.text.en
        assert entry.keywords.ru and entry.keywords.en


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


# ---------------------------------------------------------------------------
# KB wording regressions (review of run 20260929-175559, STEP 5): facts are
# unchanged, the phrasing must be unambiguous in both languages.
# ---------------------------------------------------------------------------


def test_addon_analytics_reports_are_addon_only() -> None:
    by_id = {e.id: e for e in load_kb()}
    ru = by_id["addon-analytics"].text.ru
    en = by_id["addon-analytics"].text.en
    # manager-level reports exist ONLY in the paid add-on ...
    assert "только" in ru, ru
    assert "only" in en, en
    # ... and are NOT included in the plan price
    assert "не входит" in ru, ru
    assert "not included" in en, en
    # facts unchanged
    assert by_id["addon-analytics"].facts == {"price_rub_per_month": 4900}


def test_plan_enterprise_uses_over_50_wording() -> None:
    by_id = {e.id: e for e in load_kb()}
    assert "свыше 50" in by_id["plan-enterprise"].text.ru
    assert "от 50" not in by_id["plan-enterprise"].text.ru
    assert "over 50" in by_id["plan-enterprise"].text.en
    assert by_id["plan-enterprise"].facts == {"min_users": 50, "uptime_percent": 99.9}


def test_plan_start_ru_text_has_no_english_gloss() -> None:
    import re

    ru = next(e for e in load_kb() if e.id == "plan-start").text.ru
    assert not re.search(r"[A-Za-z]", ru), ru
    assert "общий ящик" in ru
    assert "990" in ru and "5" in ru
