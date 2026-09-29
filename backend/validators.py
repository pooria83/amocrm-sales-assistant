"""Output validators (CONTEXT §17), run in order:

schema_ok → candidates_ok → language_ok → numbers_ok → no_leakage → length_ok

Any failure ⇒ one retry with a stricter reminder ⇒ templated fallback (§18).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from backend.llm import LlmOutput
from backend.models import DealContext
from backend.retriever import Match
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


# ---------------------------------------------------------------------------
# Fact-aware numeric guardrail (CONTEXT §3, principle 4).
#
# A bare "the number appears somewhere" check is too weak (a 25% discount
# would pass if 25 appears elsewhere as a seat count). Claims are extracted
# as (value, unit) pairs and matched against a typed allowlist:
#   - KB facts of the retrieved entries (unit from the fact key name)
#   - deal-context seat numbers (users)
#   - numbers the customer wrote themselves — same unit, EXCEPT percent:
#     customer percentages (competitor discounts, injection attempts) are
#     deliberately not allowlisted (§8 numeric trap / prompt-injection case).
# ---------------------------------------------------------------------------

_NUM = r"\d[\d\s\u00a0,\.]*"

PERCENT_RE = re.compile(rf"({_NUM})\s*(?:%|percent\b|процент\w*)", re.I)
RUB_RE = re.compile(rf"({_NUM})\s*(?:₽|руб\w*|rub\b)", re.I)
USERS_RE = re.compile(
    rf"({_NUM})\s*(?:пользовател\w*|сотрудник\w*|человек\w*|user\w*|seat\w*|мест(?:а|ов)?)\b",
    re.I,
)
DAYS_RE = re.compile(r"(\d+)\s*(?:дн\w*|день|дня|days?\b)", re.I)
HOURS_RE = re.compile(r"(\d+)\s*[-\s]?(?:час\w*|hours?\b)", re.I)
BARE_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\b")

UNITS = ("percent", "rub", "users", "days", "hours")


@dataclass(frozen=True)
class Claim:
    value: float
    unit: str  # percent | rub | users | days | hours | bare
    raw: str


def _normalize_number(raw: str) -> float:
    """1 990 / 1,990 / 1990 → 1990; 99,9 → 99.9."""
    s = raw.replace("\u00a0", " ").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if head and len(tail) == 3:
            s = head + tail
        else:
            s = head + "." + tail
    return float(s) if s else 0.0


def extract_claims(text: str) -> list[Claim]:
    """Typed numeric claims; unit-matched spans are masked before bare scan."""
    claims: list[Claim] = []
    masked = text
    for regex, unit in (
        (PERCENT_RE, "percent"),
        (RUB_RE, "rub"),
        (USERS_RE, "users"),
        (DAYS_RE, "days"),
        (HOURS_RE, "hours"),
    ):
        for m in regex.finditer(masked):
            claims.append(Claim(value=_normalize_number(m.group(1)), unit=unit, raw=m.group(0)))
        masked = regex.sub(" ", masked)
    for m in BARE_RE.finditer(masked):
        claims.append(Claim(value=_normalize_number(m.group(1)), unit="bare", raw=m.group(0)))
    return claims


def _unit_for_fact(key: str) -> str | None:
    k = key.lower()
    if "percent" in k:
        return "percent"
    if "rub" in k or "price" in k:
        return "rub"
    if "users" in k or "seats" in k:
        return "users"
    if "days" in k:
        return "days"
    if "hours" in k:
        return "hours"
    return None


def allowed_numbers(
    matches: Sequence[Match], deal: DealContext, customer_message: str
) -> dict[str, set[float]]:
    allowed: dict[str, set[float]] = {unit: set() for unit in UNITS}
    for match in matches:
        for key, value in match.entry.facts.items():
            unit = _unit_for_fact(key)
            if unit is not None and isinstance(value, int | float):
                allowed[unit].add(float(value))
    for seats in (deal.seats_used, deal.seat_limit):
        if seats > 0:
            allowed["users"].add(float(seats))
    for claim in extract_claims(customer_message):
        if claim.unit in allowed and claim.unit != "percent":
            allowed[claim.unit].add(claim.value)
    return allowed


def check_numbers(
    reply: str,
    *,
    matches: Sequence[Match],
    deal: DealContext,
    customer_message: str,
) -> tuple[bool, list[Claim]]:
    """numbers_ok: every typed claim is backed by an allowlisted fact."""
    allowed = allowed_numbers(matches, deal, customer_message)
    union = set().union(*allowed.values())
    claims = extract_claims(reply)
    for claim in claims:
        pool = union if claim.unit == "bare" else allowed[claim.unit]
        if claim.value not in pool:
            return False, claims
    return True, claims
