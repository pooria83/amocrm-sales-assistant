from backend.rules import detect_intent

CASES = [
    ("Сколько пользователей можно подключить на тарифе Старт?", "limits"),
    ("Какой лимит пользователей на старте?", "limits"),
    ("How many seats are included?", "limits"),
    ("В целом нравится, но дороговато для нас. Есть скидки?", "objection"),
    ("Мы сравниваем вас с конкурентом", "objection"),
    ("We need analytics reports and conversion funnels", "reporting"),
    ("We want to connect 1C and get reports by manager — is that possible?", "reporting"),
    ("Нужен срочный ответ и надёжная поддержка", "support"),
    ("Сколько стоит тариф?", "pricing"),
    ("Скидка при годовой оплате?", "pricing"),
    ("Do you offer a discount for annual billing?", "pricing"),
    ("Как подключить Telegram?", "integration"),
    ("Есть интеграция с 1C?", "integration"),
    ("Как дела?", "other"),
]


def test_intent_detection_matrix() -> None:
    for message, expected in CASES:
        assert detect_intent(message) == expected, (message, expected)


def test_empty_message_is_other() -> None:
    assert detect_intent("!!! ???") == "other"


def test_short_price_is_pricing() -> None:
    assert detect_intent("Price?") == "pricing"


def test_headcount_person_phrase_is_limits() -> None:
    assert detect_intent("Для нашей команды в 80 человек какой тариф?") == "limits"


def test_how_much_is_pricing_not_objection() -> None:
    # regression: EN phrase "too much" used to collapse to "much" after
    # stopword removal, so every "How much ...?" read as an objection
    assert detect_intent("How much does the Business plan cost per user?") == "pricing"


def test_pricey_still_detected_as_objection() -> None:
    assert detect_intent("This is too pricey for us") == "objection"


def test_bare_much_is_not_objection() -> None:
    assert detect_intent("It is much faster than before") == "other"
