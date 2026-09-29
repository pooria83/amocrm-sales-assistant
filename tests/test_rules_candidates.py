from backend.models import DealContext
from backend.retriever import get_retriever
from backend.rules import detect_intent, find_candidates


def deal(**overrides) -> DealContext:
    base = dict(
        contact="Тест",
        company="ООО «Вектор»",
        plan="start",
        seats_used=3,
        seat_limit=5,
        addons_owned=[],
        stage="client",
    )
    base.update(overrides)
    return DealContext(**base)


def matches_for(message: str):
    return get_retriever().search(message)


def test_s1_seats_near_limit_upsells_business() -> None:
    message = "Сколько пользователей можно подключить на тарифе Старт и есть ли интеграция с Telegram?"
    candidates = find_candidates(matches_for(message), detect_intent(message), deal(seats_used=5, seat_limit=5), message)
    assert [c.id for c in candidates.upsell] == ["plan-business"]
    assert candidates.upsell[0].rule == "seats_near_limit"
    assert candidates.cross_sell == []


def test_s2_objection_trial_cross_sells_onboarding() -> None:
    message = "В целом нравится, но дороговато для нас. Есть скидки?"
    candidates = find_candidates(
        matches_for(message),
        detect_intent(message),
        deal(plan="business", seats_used=12, seat_limit=50, stage="trial"),
        message,
    )
    assert candidates.upsell == []
    assert [c.id for c in candidates.cross_sell] == ["addon-onboarding"]
    assert candidates.cross_sell[0].rule == "price_objection_onboarding"


def test_s2_objection_at_client_stage_no_cross_sell() -> None:
    message = "Дороговато для нас, есть скидки?"
    candidates = find_candidates(
        matches_for(message), detect_intent(message), deal(stage="client"), message
    )
    assert candidates.cross_sell == []


def test_s3_reporting_interest_cross_sells_analytics() -> None:
    message = "We want to connect 1C and get reports by manager — is that possible?"
    candidates = find_candidates(
        matches_for(message),
        detect_intent(message),
        deal(plan="business", seats_used=20, seat_limit=50),
        message,
    )
    assert [c.id for c in candidates.cross_sell] == ["addon-analytics"]
    assert candidates.cross_sell[0].rule == "reporting_interest"
    assert candidates.upsell == []


def test_feature_needs_higher_plan_whatsapp_on_start() -> None:
    message = "Как подключить WhatsApp?"
    candidates = find_candidates(matches_for(message), detect_intent(message), deal(), message)
    assert [c.id for c in candidates.upsell] == ["plan-business"]
    assert candidates.upsell[0].rule == "feature_needs_higher_plan"


def test_enterprise_scale_by_user_count() -> None:
    message = "Нам нужно 60 пользователей на выделенном сервере"
    candidates = find_candidates(matches_for(message), detect_intent(message), deal(), message)
    assert [c.id for c in candidates.upsell] == ["plan-enterprise"]
    assert candidates.upsell[0].rule == "enterprise_scale"


def test_enterprise_scale_by_sso_request() -> None:
    message = "Нужен вход по SSO для всей компании"
    candidates = find_candidates(matches_for(message), detect_intent(message), deal(), message)
    assert [c.id for c in candidates.upsell] == ["plan-enterprise"]


def test_owned_addons_are_not_recommended() -> None:
    msg_reports = "Нужны отчёты по аналитике и конверсии"
    candidates = find_candidates(
        matches_for(msg_reports),
        detect_intent(msg_reports),
        deal(plan="business", addons_owned=["addon-analytics"]),
        msg_reports,
    )
    assert candidates.cross_sell == []

    msg_support = "Нужна срочная поддержка и sla"
    candidates = find_candidates(
        matches_for(msg_support),
        detect_intent(msg_support),
        deal(addons_owned=["addon-priority-support"]),
        msg_support,
    )
    assert candidates.cross_sell == []


def test_no_rules_fired_returns_empty() -> None:
    candidates = find_candidates([], "other", deal(), "Просто приветствие")
    assert candidates.upsell == []
    assert candidates.cross_sell == []


def test_enterprise_deal_never_upsells_to_itself() -> None:
    message = "Нужен SSO и 60 мест"
    candidates = find_candidates(
        matches_for(message),
        detect_intent(message),
        deal(plan="enterprise", seats_used=10, seat_limit=100),
        message,
    )
    assert candidates.upsell == []


def test_upsell_cap_is_one() -> None:
    message = "Нужно 60 пользователей"
    candidates = find_candidates(
        matches_for(message),
        detect_intent(message),
        deal(seats_used=5, seat_limit=5),
        message,
    )
    assert len(candidates.upsell) == 1
    # explicit scale request outranks the seat-based next plan
    assert candidates.upsell[0].id == "plan-enterprise"
