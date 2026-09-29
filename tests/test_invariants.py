"""Harness invariants (STEP 6): run on EVERY case, independent of the
per-case expectations, so a green run really means something."""

from backend.invariants import evaluate_invariants


def base_assist(text="На тарифе «Старт» до 5 пользователей.", hints=None) -> dict:
    hints = hints or {}
    return {
        "customer_reply": {"text": text, "lang": "ru", "kb_refs": ["plan-start"]},
        "internal_sales_hints": {
            "lang": "ru",
            "upsell": hints.get("upsell", []),
            "cross_sell": hints.get("cross_sell", []),
            "notes": hints.get("notes", ""),
        },
        "validation": {"fallback_used": False},
        "detected_lang": "ru",
        "grounded": True,
    }


def base_retrieve(threshold=2.5) -> dict:
    return {
        "matches": [{"id": "plan-start", "score": 9.3, "matched_terms": [],
                     "title": "Тариф «Старт»"}],
        "threshold": threshold,
        "grounded": True,
        "detected_lang": "ru",
        "lang_source": "message",
    }


def names(checks):
    return {c["name"] for c in checks}


def test_clean_response_passes_all_invariants() -> None:
    checks = evaluate_invariants(
        {"message": "Сколько пользователей на тарифе Старт?", "ui_lang": "ru"},
        base_retrieve(),
        base_assist(),
    )
    assert len(checks) == 5, names(checks)
    assert all(c["ok"] for c in checks), [(c["name"], c["actual"]) for c in checks if not c["ok"]]


def test_cjk_reply_fails_script_invariant() -> None:
    checks = evaluate_invariants(
        {"message": "Мне нужно подумать", "ui_lang": "ru"},
        base_retrieve(),
        base_assist("Здравствуйте! ——客户回复部分——"),
    )
    failed = {c["name"] for c in checks if not c["ok"]}
    assert "invariant: script whitelist" in failed
    assert "invariant: no meta markers" in failed


def test_manager_referral_fails_invariant() -> None:
    checks = evaluate_invariants(
        {"message": "Сколько пользователей?", "ui_lang": "ru"},
        base_retrieve(),
        base_assist("Обратитесь к нашему менеджеру за подробностями."),
    )
    failed = {c["name"] for c in checks if not c["ok"]}
    assert "invariant: no manager referral" in failed


def test_overlong_reply_fails_length_invariant() -> None:
    checks = evaluate_invariants(
        {"message": "Сколько?", "ui_lang": "ru"},
        base_retrieve(),
        base_assist("х" * 451),
    )
    failed = {c["name"] for c in checks if not c["ok"]}
    assert "invariant: reply <= 450 chars" in failed


def test_unallowed_candidate_title_fails_invariant() -> None:
    # plan-enterprise: not in the message, score below threshold
    retrieve = base_retrieve()
    retrieve["matches"] = [
        {"id": "plan-start", "score": 3.29, "matched_terms": [], "title": "Тариф «Старт»"},
        {"id": "plan-enterprise", "score": 1.02, "matched_terms": [], "title": "Тариф «Энтерпрайз»"},
    ]
    checks = evaluate_invariants(
        {"message": "Сколько стоят тарифы у вас?", "ui_lang": "ru"},
        retrieve,
        base_assist(
            "Если нужна команда от 50 пользователей, рассмотрите тариф «Энтерпрайз»."
        ),
    )
    failed = {c["name"] for c in checks if not c["ok"]}
    assert "invariant: no unallowed plan/add-on title in reply" in failed


def test_retrieved_title_is_allowed_in_invariant() -> None:
    checks = evaluate_invariants(
        {"message": "Как подключить WhatsApp?", "ui_lang": "ru"},
        base_retrieve(),
        base_assist("Интеграция с WhatsApp доступна на тарифе «Бизнес».", hints={
            "cross_sell": [{"id": "addon-analytics", "title": "Расширенная аналитика",
                            "reason": "r", "talking_point": "t"}],
        }),
    )
    retrieve = base_retrieve()
    retrieve["matches"] = [
        {"id": "int-whatsapp", "score": 6.0, "matched_terms": [], "title": "WhatsApp"},
        {"id": "plan-business", "score": 3.5, "matched_terms": [], "title": "Тариф «Бизнес»"},
    ]
    checks = evaluate_invariants(
        {"message": "Как подключить WhatsApp?", "ui_lang": "ru"},
        retrieve,
        base_assist("Интеграция с WhatsApp доступна на тарифе «Бизнес»."),
    )
    assert all(c["ok"] for c in checks), [(c["name"], c["actual"]) for c in checks if not c["ok"]]


def test_hint_fields_are_script_checked() -> None:
    checks = evaluate_invariants(
        {"message": "Мне нужно подумать", "ui_lang": "ru"},
        base_retrieve(),
        base_assist(
            "Всё готово.",
            hints={"cross_sell": [{"id": "addon-onboarding", "title": "Пакет",
                                   "reason": "客户回复", "talking_point": "t"}]},
        ),
    )
    failed = {c["name"] for c in checks if not c["ok"]}
    assert "invariant: script whitelist" in failed
