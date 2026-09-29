from backend.retriever import get_retriever, tokenize


def _retriever():
    return get_retriever()


def test_russian_happy_path_query() -> None:
    matches, threshold, grounded = _retriever().retrieve(
        "Сколько пользователей можно подключить на тарифе Старт?"
    )
    assert grounded, f"expected grounded, got {[(m.entry.id, m.score) for m in matches]}"
    assert matches[0].entry.id == "plan-start"
    assert matches[0].score >= threshold
    assert matches[0].matched_terms


def test_telegram_query_matches_integration() -> None:
    matches, _, grounded = _retriever().retrieve(
        "Есть ли интеграция с Telegram в вашем сервисе?"
    )
    assert grounded
    ids = [m.entry.id for m in matches]
    assert "int-telegram" in ids


def test_english_query_matches_russian_index() -> None:
    matches, _, grounded = _retriever().retrieve(
        "Do you have a Telegram integration?"
    )
    assert grounded, [(m.entry.id, m.score) for m in matches]
    assert matches[0].entry.id == "int-telegram"


def test_english_1c_and_analytics_query() -> None:
    matches, _, grounded = _retriever().retrieve(
        "We want to connect 1C and get reports by manager — is that possible?"
    )
    assert grounded, [(m.entry.id, m.score) for m in matches]
    ids = [m.entry.id for m in matches]
    assert "int-1c" in ids or "addon-analytics" in ids


def test_price_objection_query() -> None:
    matches, _, grounded = _retriever().retrieve(
        "В целом нравится, но дороговато для нас. Есть скидки?"
    )
    assert grounded, [(m.entry.id, m.score) for m in matches]
    ids = [m.entry.id for m in matches]
    assert "obj-too-expensive" in ids or "billing-cycles" in ids


def test_out_of_scope_query_is_ungrounded() -> None:
    matches, threshold, grounded = _retriever().retrieve(
        "Сможете сделать для нас кастомное мобильное приложение под iOS?"
    )
    assert not grounded, ([(m.entry.id, m.score) for m in matches], threshold)


def test_morphological_query_variants_match() -> None:
    queries = [
        "Сколько стоит тариф?",
        "Сколько стоят тарифы у вас?",
        "Нужен тариф для нашей команды",
    ]
    for query in queries:
        matches, _, grounded = _retriever().retrieve(query)
        assert grounded, (query, [(m.entry.id, m.score) for m in matches])


def test_matched_terms_are_stems_present_in_query() -> None:
    query = "Сколько пользователей на тарифе Старт?"
    matches, _, _ = _retriever().retrieve(query)
    query_stems = set(tokenize(query))
    assert matches
    assert set(matches[0].matched_terms) <= query_stems


def test_title_bonus_fixes_plan_specific_rank1() -> None:
    """Regression (mcp run 20260929-155851, hit@1 misses fixed by the
    deterministic title bonus in retriever.search)."""
    cases = {
        "Сколько стоит тариф Бизнес за пользователя в месяц?": "plan-business",
        "Какие функции входят в тариф Старт?": "plan-start",
        "How much does the Business plan cost per user?": "plan-business",
    }
    for query, expected in cases.items():
        matches, _, grounded = _retriever().retrieve(query)
        assert grounded, query
        assert matches[0].entry.id == expected, (query, [(m.entry.id, m.score) for m in matches])


def test_title_bonus_keeps_no_match_ungrounded() -> None:
    for query in (
        "Сможете сделать нам игру на Unity?",
        "Do you resell office furniture?",
    ):
        matches, _, grounded = _retriever().retrieve(query)
        assert not grounded, (query, [(m.entry.id, m.score) for m in matches])
