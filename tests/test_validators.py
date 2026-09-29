from backend.llm import LlmOutput, Reason
from backend.rules import Candidate, Candidates
from backend.validators import enforce_candidates, parse_output

CANDIDATES = Candidates(
    upsell=[Candidate(id="plan-business", rule="seats_near_limit")],
    cross_sell=[
        Candidate(id="addon-onboarding", rule="price_objection_onboarding"),
        Candidate(id="addon-analytics", rule="reporting_interest"),
    ],
)


def good_output() -> LlmOutput:
    return LlmOutput(
        customer_reply="Здравствуйте! На тарифе «Старт» до 5 пользователей.",
        upsell_reasons=[
            Reason(id="plan-business", reason="Места закончились.", talking_point="Предложите «Бизнес».")
        ],
        cross_sell_reasons=[
            Reason(
                id="addon-onboarding",
                reason="Клиент на пробном периоде.",
                talking_point="Предложите помощь с настройкой.",
            ),
            Reason(
                id="addon-analytics",
                reason="Нужны отчёты.",
                talking_point="Покажите отчёты по менеджерам.",
            ),
        ],
    )


def test_parse_valid_output() -> None:
    parsed = {
        "customer_reply": "Здравствуйте!",
        "upsell_reasons": [],
        "cross_sell_reasons": [],
    }
    output = parse_output(parsed)
    assert output is not None
    assert output.customer_reply == "Здравствуйте!"


def test_parse_missing_required_field_fails() -> None:
    assert parse_output({"customer_reply": "Привет"}) is None


def test_parse_wrong_types_fails() -> None:
    assert parse_output(
        {"customer_reply": "Привет", "upsell_reasons": "not-a-list", "cross_sell_reasons": []}
    ) is None
    assert parse_output(
        {"customer_reply": 42, "upsell_reasons": [], "cross_sell_reasons": []}
    ) is None


def test_parse_non_object_fails() -> None:
    assert parse_output(["customer_reply"]) is None


def test_enforce_candidates_accepts_exact_match() -> None:
    cleaned, problems = enforce_candidates(good_output(), CANDIDATES)
    assert problems == []
    assert [r.id for r in cleaned.upsell_reasons] == ["plan-business"]
    assert [r.id for r in cleaned.cross_sell_reasons] == ["addon-onboarding", "addon-analytics"]


def test_enforce_candidates_drops_unknown_ids() -> None:
    output = good_output()
    output.upsell_reasons.append(Reason(id="plan-enterprise", reason="x", talking_point="y"))
    output.cross_sell_reasons.append(Reason(id="addon-priority-support", reason="x", talking_point="y"))
    cleaned, problems = enforce_candidates(output, CANDIDATES)
    assert [r.id for r in cleaned.upsell_reasons] == ["plan-business"]
    assert [r.id for r in cleaned.cross_sell_reasons] == ["addon-onboarding", "addon-analytics"]
    assert any("plan-enterprise" in p for p in problems)
    assert any("addon-priority-support" in p for p in problems)


def test_enforce_candidates_reports_missing_candidates() -> None:
    output = LlmOutput(customer_reply="Привет", upsell_reasons=[], cross_sell_reasons=[])
    cleaned, problems = enforce_candidates(output, CANDIDATES)
    assert any("plan-business" in p for p in problems)
    assert any("addon-onboarding" in p for p in problems)
    assert any("addon-analytics" in p for p in problems)
    assert cleaned.upsell_reasons == []


def test_enforce_candidates_with_empty_candidates() -> None:
    output = LlmOutput(
        customer_reply="Привет",
        upsell_reasons=[Reason(id="plan-business", reason="x", talking_point="y")],
        cross_sell_reasons=[],
    )
    cleaned, problems = enforce_candidates(output, Candidates())
    assert cleaned.upsell_reasons == []
    assert problems  # unknown id reported
