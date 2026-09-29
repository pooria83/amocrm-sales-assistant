from backend.retriever import tokenize


def test_russian_morphological_variants_share_stem() -> None:
    stems = [tokenize(word) for word in ["тариф", "тарифы", "тарифа", "тарифом"]]
    assert all(s == ["тариф"] for s in stems)


def test_russian_sentence_tokenization() -> None:
    tokens = tokenize("Сколько пользователей на тарифе Старт?")
    assert tokens == ["скольк", "пользовател", "тариф", "старт"]


def test_latin_and_cyrillic_one_c_unified() -> None:
    assert tokenize("1С") == tokenize("1c") == ["1c"]


def test_cyrillic_words_with_letter_c_unaffected() -> None:
    # regression: normalising "с" must not touch regular Russian words
    assert tokenize("сколько")[0] == "скольк"
    assert tokenize("старт")[0] == "старт"


def test_stopwords_dropped_in_both_languages() -> None:
    assert "on" not in tokenize("on the plan")
    assert "на" not in tokenize("на тарифе")


def test_numbers_preserved() -> None:
    tokens = tokenize("скидка 20% и цена 1990")
    assert "20" in tokens
    assert "1990" in tokens


def test_english_stemming() -> None:
    assert tokenize("plans") == tokenize("plan") == ["plan"]
    assert tokenize("users") == ["user"]


def test_brand_tokens_kept_verbatim() -> None:
    assert "telegram" in tokenize("Подключите Telegram")
    assert "whatsapp" in tokenize("Как насчет WhatsApp?")
