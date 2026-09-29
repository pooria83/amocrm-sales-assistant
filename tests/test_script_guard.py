"""Regression tests for the defects found in MCP run 20260929-175559.

Each test quotes the EXACT string that reached the customer (or the exact
claim that must be blocked). Before the fix these fail: the new validators
do not exist yet or the length limit is still 600.

Covered defects:
- ru31 / x13: Chinese text and template artifacts passed language+leakage
  (script whitelist + meta markers must reject them);
- ru01 / ru22 / x06: the reply is written BY the manager yet tells the
  customer to "contact the manager" (manager-referral rule);
- ru01 / ru22: plan upsell pitches inside the customer text (title rule);
- ru18: reports claimed to be included in the plan (KB wording + title rule);
- length limit lowered 600 → 450 (STEP 3).
"""

from backend.kb import get_kb
from backend.llm import LlmOutput, Reason
from backend.retriever import Match, get_threshold
from backend.rules import Candidate, Candidates
from backend.validators import (
    MAX_REPLY_CHARS,
    check_leakage,
    check_length,
    check_manager_referral,
    check_meta_markers,
    check_output_script,
    check_script,
)

# --- exact bad strings from run 20260929-175559 ---------------------------

RU31_CHINESE_REPLY = (
    "Здравствуйте! Мы понимаем, что вам нужно время на принятие решения. "
    "Предлагаю воспользоваться пробным периодом на 14 дней, чтобы оценить все "
    "функции тарифа «Бизнес». Дату обратной связи我们可以继续这部分，但以俄语完成。"
    "以下是完整的回复：——客户回复部分——客户回复部分已经完成。接下来是内部建议部分。"
    "——内部建议部分——"
)

X13_CHINESE_REPLY = (
    "Пробный период на тарифе «Бизнес» составляет 14 дней бесплатно, без "
    "необходимости в банковской карте. В期间，系统已截断您的输入。请您按照提供的"
    "中文模板继续填写。以下是继续填写的部分，假设客户询问的是关于试用期的问题，"
    "并且我们有相关的知识库信息可以参考。我们将按照给定的格式和规则进行回复。"
    "请继续填写客户回复部分。——销售助手"
)

RU01_REFERRAL_REPLY = (
    "Добрый день, Алексей! На тарифе «Старт» можно подключить до 5 пользователей. "
    "Ваши текущие лимиты соответствуют этому тарифу, поэтому вы можете использовать "
    "все его функции, включая общую входящую и интеграцию с Telegram. Если вам "
    "понадобится больше пользователей, вы можете обратиться к нашему менеджеру для "
    "перехода на тариф «Бизнес». Уточните детали и стоимость с ним."
)

RU22_REFERRAL_PITCH_REPLY = (
    "Тариф «Старт» стоит 990 ₽ за пользователя в месяц, включая до 5 пользователей. "
    "Для команд от 50 пользователей доступен тариф «Энтерпрайз», но цена "
    "рассчитывается индивидуально. Если вам нужно больше пользователей, рекомендуем "
    "обратиться к менеджеру для получения точной информации о тарифе «Энтерпрайз» "
    "и других возможностях. Уточните детали, пожалуйста, у вашего менеджера для "
    "получения точного расчета и дополнительных предложений."
)

X06_REFERRAL_REPLY = (
    "На тарифе «Старт» лимит пользователей — до 5. Чтобы подключить больше "
    "сотрудников, нужно перейти на следующий тариф. Подробности можно уточнить у "
    "менеджера. Ваши текущие лимиты: до 5 пользователей на тарифе «Старт»."
)

RU18_WRONG_FACT_REPLY = (
    "Да, в тарифе «Бизнес» и выше доступны отчёты по менеджерам. "
    "Если хотите узнать больше, могу рассказать подробнее."
)

RU22_MSG = "Сколько стоят тарифы у вас?"
RU01_MSG = "Сколько пользователей можно подключить на тарифе Старт?"
RU18_MSG = "Есть отчёты по менеджерам?"
X06_MSG = "Сколько сотрудников можно добавить на старте?"

THRESHOLD = get_threshold()


def entry(entry_id: str):
    return next(e for e in get_kb() if e.id == entry_id)


def match(entry_id: str, score: float) -> Match:
    return Match(entry=entry(entry_id), score=score, matched_terms=[])


def output(reply: str, candidates: Candidates | None = None) -> LlmOutput:
    return LlmOutput(customer_reply=reply, upsell_reasons=[], cross_sell_reasons=[])


# --- STEP 2: script whitelist + meta markers ------------------------------


def test_ru31_chinese_reply_flagged_by_script_whitelist() -> None:
    problems = check_script(RU31_CHINESE_REPLY)
    assert problems, "CJK in the customer reply must fail the script whitelist"


def test_ru31_template_artifacts_flagged_as_meta_markers() -> None:
    problems = check_meta_markers(RU31_CHINESE_REPLY)
    assert problems
    assert any("——" in p or "客户" in p for p in problems)


def test_x13_chinese_reply_flagged() -> None:
    assert check_script(X13_CHINESE_REPLY)
    assert check_meta_markers(X13_CHINESE_REPLY)


def test_clean_ru_reply_passes_script_whitelist() -> None:
    clean = (
        "Здравствуйте, Алексей! На тарифе «Старт» — до 5 пользователей, "
        "цена 990 ₽ за пользователя в месяц (20 % при оплате за год). "
        "Номер заявки: №42."
    )
    assert check_script(clean) == []
    assert check_meta_markers(clean) == []


def test_clean_en_reply_passes_script_whitelist() -> None:
    clean = "Hello! The Start plan costs 990 RUB/user/month — up to 5 users."
    assert check_script(clean) == []
    assert check_meta_markers(clean) == []


def test_output_script_covers_internal_hint_fields() -> None:
    bad = LlmOutput(
        customer_reply="Всё готово.",
        upsell_reasons=[
            Reason(id="addon-onboarding", reason="客户回复部分", talking_point="ok")
        ],
        cross_sell_reasons=[],
    )
    problems = check_output_script(bad)
    assert problems, "internal hint fields must be script-checked too"


def test_output_script_accepts_normal_reasons() -> None:
    good = LlmOutput(
        customer_reply="На тарифе «Старт» до 5 пользователей.",
        upsell_reasons=[
            Reason(
                id="plan-business",
                reason="Клиент подошёл к лимиту мест: 5 из 5.",
                talking_point="Предложите «Бизнес» — до 50 пользователей.",
            )
        ],
        cross_sell_reasons=[],
    )
    assert check_output_script(good) == []


def test_meta_marker_list_contains_review_evidence() -> None:
    from backend.validators import META_MARKERS

    for marker in ("——", "客户", "part 1", "part 2", "customer_reply", "internal", "<kb>", "```"):
        assert marker in META_MARKERS, marker


# --- STEP 3: the reply is written BY the manager --------------------------


def test_ru01_exact_reply_has_manager_referral() -> None:
    assert check_manager_referral(RU01_REFERRAL_REPLY)


def test_ru22_exact_reply_has_manager_referral() -> None:
    assert check_manager_referral(RU22_REFERRAL_PITCH_REPLY)


def test_x06_exact_reply_has_manager_referral() -> None:
    assert check_manager_referral(X06_REFERRAL_REPLY)


def test_en_manager_referral_rejected() -> None:
    assert check_manager_referral("Please contact our manager for pricing details.")
    assert check_manager_referral("You can ask your manager to clarify.")


def test_legit_manager_phrases_are_not_referrals() -> None:
    allowed = [
        "Точная сумма будет подтверждена менеджером.",
        "The exact total will be confirmed by the manager.",
        "В тарифе «Энтерпрайз» входит персональный менеджер и SSO.",
        "Enterprise includes a dedicated manager and SSO.",
    ]
    for text in allowed:
        assert check_manager_referral(text) == [], text


def test_length_limit_is_450() -> None:
    assert MAX_REPLY_CHARS == 450
    assert check_length("х" * 450)
    assert not check_length("х" * 451)


def test_ru22_is_within_length_but_caught_by_referral() -> None:
    # The exact ru22 reply is 433 chars: length alone would not catch it.
    assert len(RU22_REFERRAL_PITCH_REPLY) == 433
    assert check_length(RU22_REFERRAL_PITCH_REPLY)
    assert check_manager_referral(RU22_REFERRAL_PITCH_REPLY)


# --- STEP 4: plan/add-on titles in the customer text ----------------------


def _leak(reply: str, message: str, matches: list[Match], candidates: Candidates) -> list[str]:
    return check_leakage(
        output(reply), candidates, message=message, matches=matches, threshold=THRESHOLD
    )


def test_ru22_enterprise_pitch_blocked() -> None:
    problems = _leak(
        RU22_REFERRAL_PITCH_REPLY,
        RU22_MSG,
        [match("plan-start", 3.29), match("plan-enterprise", 1.02)],
        Candidates(),
    )
    assert any("Энтерпрайз" in p or "enterprise" in p for p in problems), problems


def test_ru01_business_pitch_blocked_but_start_allowed() -> None:
    problems = _leak(
        RU01_REFERRAL_REPLY,
        RU01_MSG,
        [match("plan-start", 9.34), match("limit-seats", 6.04)],
        Candidates(upsell=[Candidate(id="plan-business", rule="seats_near_limit")]),
    )
    assert any("Бизнес" in p or "business" in p for p in problems), problems
    # «Старт» stays allowed: the customer asked about it.
    assert not any("Старт" in p or "start" in p for p in problems), problems


def test_ru18_reports_plan_claim_blocked() -> None:
    problems = _leak(
        RU18_WRONG_FACT_REPLY,
        RU18_MSG,
        [match("addon-analytics", 6.94), match("plan-enterprise", 2.75)],
        Candidates(
            cross_sell=[Candidate(id="addon-analytics", rule="reporting_interest")]
        ),
    )
    assert any("Бизнес" in p or "business" in p for p in problems), problems


def test_whatsapp_on_business_allowed_when_retrieved() -> None:
    reply = "Интеграция с WhatsApp доступна на тарифе «Бизнес»."
    problems = _leak(
        reply,
        "Как подключить WhatsApp?",
        [match("int-whatsapp", 6.0), match("plan-business", 3.5)],
        Candidates(),
    )
    assert problems == [], problems


def test_plan_named_by_customer_allowed() -> None:
    reply = "Пробный период на тарифе «Бизнес» длится 14 дней."
    problems = _leak(
        reply,
        "Как выглядит пробный период на Бизнесе?",
        [match("trial", 7.4)],
        Candidates(),
    )
    assert problems == [], problems


def test_addon_named_in_reply_allowed_when_retrieved() -> None:
    reply = (
        "Отчёты по менеджерам — в платном дополнении «Расширенная аналитика», "
        "4 900 ₽ в месяц."
    )
    problems = _leak(
        reply,
        RU18_MSG,
        [match("addon-analytics", 6.94)],
        Candidates(cross_sell=[Candidate(id="addon-analytics", rule="reporting_interest")]),
    )
    assert problems == [], problems
