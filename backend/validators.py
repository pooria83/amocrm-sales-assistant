"""Output validators (CONTEXT §17), run in order:

schema_ok → candidates_ok → language_ok → numbers_ok → no_leakage → length_ok

Any failure ⇒ one retry with a stricter reminder ⇒ templated fallback (§18).
"""

from dataclasses import dataclass, field

from pydantic import ValidationError

from backend.llm import LlmOutput
from backend.rules import Candidates

MAX_REPLY_CHARS = 600


@dataclass
class Validation:
    schema_ok: bool = False
    candidates_ok: bool = False
    language_ok: bool = False
    numbers_ok: bool = False
    no_leakage: bool = False
    length_ok: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(
            (
                self.schema_ok,
                self.candidates_ok,
                self.language_ok,
                self.numbers_ok,
                self.no_leakage,
                self.length_ok,
            )
        )


def parse_output(parsed: dict) -> LlmOutput | None:
    """schema_ok: JSON object matching the §17 shape."""
    try:
        return LlmOutput.model_validate(parsed)
    except ValidationError:
        return None


def enforce_candidates(
    output: LlmOutput, candidates: Candidates
) -> tuple[LlmOutput, list[str]]:
    """candidates_ok: every reason id ∈ rule-engine candidates.

    Returns (cleaned_output, problems): ids outside the candidate list are
    dropped, missing candidates reported (the caller fills them with
    templated reasons on the final fallback, §18).
    """
    problems: list[str] = []

    expected_upsell = {c.id for c in candidates.upsell}
    expected_cross = {c.id for c in candidates.cross_sell}

    kept_upsell = []
    for reason in output.upsell_reasons:
        if reason.id in expected_upsell:
            kept_upsell.append(reason)
        else:
            problems.append(f"unknown upsell id from model: {reason.id}")

    kept_cross = []
    for reason in output.cross_sell_reasons:
        if reason.id in expected_cross:
            kept_cross.append(reason)
        else:
            problems.append(f"unknown cross-sell id from model: {reason.id}")

    missing_upsell = expected_upsell - {r.id for r in kept_upsell}
    missing_cross = expected_cross - {r.id for r in kept_cross}
    for candidate_id in sorted(missing_upsell | missing_cross):
        problems.append(f"missing reason for candidate: {candidate_id}")

    cleaned = LlmOutput(
        customer_reply=output.customer_reply,
        upsell_reasons=kept_upsell,
        cross_sell_reasons=kept_cross,
    )
    return cleaned, problems
