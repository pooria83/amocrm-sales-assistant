"""Output validators (CONTEXT §17), run in order:

schema_ok → candidates_ok → language_ok → numbers_ok → no_leakage → length_ok

Any failure ⇒ one retry with a stricter reminder ⇒ templated fallback (§18).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from backend.language import detect_text_lang
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
# A claim with NO unit ("Пробный период — 14.") is rejected outright: we
# cannot tell which allowlist it belongs to, so the same numeral must never
# pass merely because it exists in some other unit's list (CONTEXT §3 —
# matching is same-unit). The model is asked to attach an explicit unit and
# gets one retry before the templated fallback.
# ---------------------------------------------------------------------------

_NUM = r"\d[\d\s\u00a0,\.]*"

PERCENT_RE = re.compile(rf"({_NUM})\s*[-–—]?\s*(?:%|percent\b|процент\w*)", re.I)
RUB_RE = re.compile(rf"({_NUM})\s*(?:₽|руб\w*|rub\b)", re.I)
USERS_RE = re.compile(
    rf"({_NUM})\s*\+?\s*(?:пользовател\w*|сотрудник\w*|человек\w*|user\w*|seat\w*|мест(?:а|ов)?)\b",
    re.I,
)
DAYS_RE = re.compile(r"(\d+)\s*[-\s]?(?:дн\w*|день|дня|days?\b)", re.I)
HOURS_RE = re.compile(r"(\d+)\s*[-\s]?(?:час\w*|hours?\b)", re.I)
BARE_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\b")
# Seat spans and seat-limit phrasings whose unit word attaches to the number
# but is not adjacent: "12 из 50 мест", "12 of 50 seats", "до 5", "up to 50".
# In this product's KB every such number is a seat count, so both numbers are
# typed as users; a value outside the users allowlist is still rejected.
SEAT_SPAN_RE = re.compile(
    r"(\d+)\s*(?:из|of)\s*(\d+)\s*\+?\s*"
    r"(?:мест\w*|пользовател\w*|сотрудник\w*|человек\w*|users?\b|seats?\b)",
    re.I,
)
IMPLIED_USERS_RE = re.compile(r"\b(?:до|от|up\s+to|from)\s+(\d+)", re.I)
# Unit word BEFORE the number: "количество пользователей — 5", "users: 5".
USERS_AFTER_RE = re.compile(
    rf"(?:пользовател\w*|сотрудник\w*|человек\w*|user\w*|seat\w*|мест(?:а|ов)?)"
    rf"\s*(?:[—–-]|:|is|=)?\s*({_NUM})",
    re.I,
)

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
    """Typed numeric claims; unit-matched spans are masked before bare scan.

    Order: seat spans → explicit units → implied seat limits ("до 5") → bare.
    Anything still untyped after this comes out as unit="bare" and is rejected
    by check_numbers.
    """
    claims: list[Claim] = []
    masked = text
    for m in SEAT_SPAN_RE.finditer(masked):
        claims.append(Claim(value=_normalize_number(m.group(1)), unit="users", raw=m.group(0)))
        claims.append(Claim(value=_normalize_number(m.group(2)), unit="users", raw=m.group(0)))
    masked = SEAT_SPAN_RE.sub(" ", masked)
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
    for m in USERS_AFTER_RE.finditer(masked):
        claims.append(Claim(value=_normalize_number(m.group(1)), unit="users", raw=m.group(0)))
    masked = USERS_AFTER_RE.sub(" ", masked)
    for m in IMPLIED_USERS_RE.finditer(masked):
        claims.append(Claim(value=_normalize_number(m.group(1)), unit="users", raw=m.group(0)))
    masked = IMPLIED_USERS_RE.sub(" ", masked)
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


def _is_bad_claim(claim: Claim, allowed: dict[str, set[float]]) -> bool:
    return claim.unit == "bare" or claim.value not in allowed[claim.unit]


def check_numbers(
    reply: str,
    *,
    matches: Sequence[Match],
    deal: DealContext,
    customer_message: str,
) -> tuple[bool, list[Claim]]:
    """numbers_ok: every claim carries a unit and is backed by that unit's list.

    Bare claims (no unit in the reply) fail by construction — a value that
    exists in one allowlist (e.g. 14 trial days) must not license the same
    numeral without a unit elsewhere.
    """
    allowed = allowed_numbers(matches, deal, customer_message)
    claims = extract_claims(reply)
    return not any(_is_bad_claim(c, allowed) for c in claims), claims


def find_bad_claim(
    reply: str,
    *,
    matches: Sequence[Match],
    deal: DealContext,
    customer_message: str,
) -> Claim | None:
    """The first rejected claim, so the retry reminder can name it (§17)."""
    allowed = allowed_numbers(matches, deal, customer_message)
    return next((c for c in extract_claims(reply) if _is_bad_claim(c, allowed)), None)


# Denials of a foreign number ("скидка 20%, а не 80%", "20%, not 100%") are
# the model arguing with the customer's premise — not our claim. They leak the
# rejected number into the reply, so they are stripped before validation; the
# model is separately told never to repeat customer discount percentages.
_PERCENT_DENIAL_RE = re.compile(
    r"\s*,?\s*(?:а\s+не|not)\s+\d{1,3}(?:[.,]\d{3})?\s*%", re.I
)


def strip_percent_denial(text: str) -> str:
    return _PERCENT_DENIAL_RE.sub("", text)


# ---------------------------------------------------------------------------
# Language, leakage and length checks (CONTEXT §17, validators 3/5/6)
# ---------------------------------------------------------------------------

# Markers that only ever belong to internal text; their presence in the
# customer reply means the two output blocks were mixed.
LEAK_MARKERS = (
    "допродаж",
    "upsell",
    "cross-sell",
    "crosssell",
    "внутренн",
    "примечани",
    "internal",
    "talking_point",
    "talking point",
)


def check_language(reply: str, customer_lang: str) -> bool:
    """language_ok: detected reply language == customer language."""
    return detect_text_lang(reply) == customer_lang


def check_length(reply: str) -> bool:
    """length_ok: reply present and ≤ 600 characters."""
    return 0 < len(reply) <= MAX_REPLY_CHARS


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def check_leakage(output: LlmOutput, candidates: Candidates) -> list[str]:
    """no_leakage: internal text must never appear inside customer_reply."""
    problems: list[str] = []
    reply = _norm(output.customer_reply)
    low = output.customer_reply.lower()

    for candidate in candidates.upsell + candidates.cross_sell:
        if candidate.id.lower() in low:
            problems.append(f"candidate id in reply: {candidate.id}")

    for reason in output.upsell_reasons + output.cross_sell_reasons:
        for text in (reason.reason, reason.talking_point):
            normalized = _norm(text)
            if len(normalized) >= 8 and normalized in reply:
                problems.append(f"internal text leaked into reply: {normalized[:40]}")

    for marker in LEAK_MARKERS:
        if marker in low:
            problems.append(f"internal marker in reply: {marker}")

    return problems
