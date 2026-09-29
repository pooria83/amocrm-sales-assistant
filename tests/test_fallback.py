from backend.fallback import (
    known_rules,
    no_match_note,
    no_match_reply,
    templated_reason,
    validation_failed_reply,
)
from backend.rules import ENTITLEMENT_RULES


def test_no_match_reply_ru_with_name() -> None:
    reply = no_match_reply("ru", "Алексей")
    assert reply.startswith("Здравствуйте, Алексей!")
    assert "уточню детали у команды" in reply
    assert "скидк" not in reply  # never invents offers


def test_no_match_reply_en_without_name() -> None:
    reply = no_match_reply("en")
    assert reply.startswith("Hello!")
    assert "check the details with our team" in reply


def test_no_match_note_bilingual() -> None:
    ru = no_match_note("ru")
    en = no_match_note("en")
    assert "команде решений" in ru
    assert "Допродаж не предлагаем" in ru
    assert "Escalate to the solutions team" in en
    assert "No upsell suggested" in en


def test_validation_failed_reply_bilingual() -> None:
    ru = validation_failed_reply("ru", "Ирина")
    en = validation_failed_reply("en", "Daniel")
    assert ru.startswith("Здравствуйте, Ирина!")
    assert "скоро отвечу" in ru
    assert en.startswith("Hello Daniel,")
    assert "confirming the details" in en


def test_templated_reasons_cover_every_rule() -> None:
    for rule in ENTITLEMENT_RULES:
        for lang in ("ru", "en"):
            reason, talking_point = templated_reason(rule, lang)
            assert reason and talking_point, (rule, lang)
            # must be a real template, not the generic default
            assert reason != "Допродажа подобрана по правилам.", (rule, lang)


def test_onboarding_reason_follows_phrasing_guard() -> None:
    # §15: never read as "expensive → buy another paid thing"
    reason, _ = templated_reason("price_objection_onboarding", "ru")
    assert "после обсуждения тарифа" in reason
    assert "дорог" not in reason
    assert "купите" not in reason


def test_unknown_rule_falls_back_to_generic() -> None:
    reason, talking_point = templated_reason("nonexistent_rule", "ru")
    assert reason == "Допродажа подобрана по правилам."
    assert talking_point


def test_known_rules_match_entitlement_rules() -> None:
    assert known_rules() == frozenset(ENTITLEMENT_RULES)
