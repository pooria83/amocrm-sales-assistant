from backend.language import detect_language, detect_text_lang


def test_russian_message() -> None:
    assert detect_text_lang("Сколько пользователей на тарифе Старт?") == "ru"


def test_english_message() -> None:
    assert detect_text_lang("Do you have a Telegram integration?") == "en"


def test_brand_token_ignored() -> None:
    assert detect_text_lang("Подключите Telegram") == "ru"
    assert detect_text_lang("Please connect Telegram") == "en"


def test_short_message_is_ambiguous() -> None:
    assert detect_text_lang("Price?") is None
    assert detect_text_lang("Telegram?") is None
    assert detect_text_lang("10") is None
    assert detect_text_lang("ok") is None


def test_inherits_conversation_language() -> None:
    history = [
        {"role": "customer", "text": "Здравствуйте! Мы сейчас на тарифе Старт."},
        {"role": "manager", "text": "Добрый день, Алексей!"},
    ]
    assert detect_language("Price?", history, ui_lang="en") == ("en", "conversation")
    assert detect_language("Telegram?", history, ui_lang="en") == ("en", "conversation")


def test_uses_last_detected_customer_language() -> None:
    history = [
        {"role": "customer", "text": "Hello, we are evaluating the product."},
        {"role": "manager", "text": "Hi!"},
        {"role": "customer", "text": "Добрый день, хотим продлить подписку."},
    ]
    assert detect_language("Price?", history, ui_lang="en") == ("ru", "conversation")


def test_falls_back_to_ui_language() -> None:
    assert detect_language("10", history=[], ui_lang="ru") == ("ru", "ui_default")
    assert detect_language("Price?", history=None, ui_lang="en") == ("en", "ui_default")


def test_message_language_wins_over_history() -> None:
    history = [{"role": "customer", "text": "Hello, do you have a trial?"}]
    lang, source = detect_language("Сколько стоит тариф?", history, ui_lang="ru")
    assert (lang, source) == ("ru", "message")


def test_documented_failure_transliteration() -> None:
    # Known limitation, documented in README: Latin transliteration ⇒ "en"
    assert detect_text_lang("skolko stoit") == "en"
