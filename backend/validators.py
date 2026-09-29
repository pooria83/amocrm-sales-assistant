"""Output validators (CONTEXT §17), run in order:

schema_ok → candidates_ok → language_ok → numbers_ok → capacity_ok
→ script_ok → role_ok → no_leakage → length_ok

Any failure ⇒ one retry with a stricter reminder ⇒ templated fallback (§18).

script_ok / role_ok / the plan-title part of no_leakage are regression guards
for the defects found in MCP run 20260929-175559:
- ru31 / x13 shipped Chinese text and template artifacts in the reply;
- ru01 / ru22 / x06 told the customer to "contact the manager" even though
  the reply IS the manager's message;
- ru01 / ru22 / ru18 pitched plan/add-on titles the customer never asked
  about and that were not retrieved sources.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from backend.kb import KbEntry, get_kb
from backend.language import detect_text_lang
from backend.llm import LlmOutput, Reason
from backend.models import DealContext
from backend.retriever import Match, tokenize
from backend.rules import Candidates

MAX_REPLY_CHARS = 450


@dataclass
class Validation:
    schema_ok: bool = False
    candidates_ok: bool = False
    language_ok: bool = False
    numbers_ok: bool = False
    capacity_ok: bool = False
    script_ok: bool = False
    role_ok: bool = False
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
                self.capacity_ok,
                self.script_ok,
                self.role_ok,
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
    output: LlmOutput, candidates: Candidates, ui_lang: str = "ru"
) -> tuple[LlmOutput, list[str]]:
    """candidates_ok: every reason id ∈ rule-engine candidates.

    Returns (cleaned_output, problems): ids outside the candidate list are
    dropped. Missing candidates are FILLED with the templated reason for
    their rule (CONTEXT §17: "missing ones are filled with a templated
    reason") — an omitted reason must not burn the single retry.
    """
    problems: list[str] = []

    expected_upsell = {c.id for c in candidates.upsell}
    expected_cross = {c.id for c in candidates.cross_sell}

    kept_upsell = []
    for reason in output.upsell_reasons:
        if reason.id in expected_upsell:
            kept_upsell.append(reason)
        elif reason.id in expected_cross:
            # Model filed a candidate into the wrong array (or duplicated it).
            # The candidate itself is valid — the rule engine chose it — and
            # the content is usable: re-file deterministically instead of
            # burning a retry on a cosmetic array mistake (every S3-class run
            # used to put "addon-analytics" into upsell_reasons).
            if reason.id not in {r.id for r in output.cross_sell_reasons}:
                output.cross_sell_reasons.append(reason)
        else:
            problems.append(f"unknown upsell id from model: {reason.id}")

    kept_cross = []
    for reason in output.cross_sell_reasons:
        if reason.id in expected_cross:
            kept_cross.append(reason)
        elif reason.id in expected_upsell:
            if reason.id not in {r.id for r in output.upsell_reasons}:
                output.upsell_reasons.append(reason)
        else:
            problems.append(f"unknown cross-sell id from model: {reason.id}")

    # §17: missing reasons are templated, not an error (an MCP retry used to
    # fail on exactly this: "missing reason for candidate: plan-business").
    from backend.fallback import templated_reason

    by_rule = {c.id: c.rule for c in candidates.upsell + candidates.cross_sell}
    for candidate_id in sorted(expected_upsell - {r.id for r in kept_upsell}):
        reason, talk = templated_reason(by_rule.get(candidate_id, "unknown"), ui_lang)
        kept_upsell.append(Reason(id=candidate_id, reason=reason, talking_point=talk))
    for candidate_id in sorted(expected_cross - {r.id for r in kept_cross}):
        reason, talk = templated_reason(by_rule.get(candidate_id, "unknown"), ui_lang)
        kept_cross.append(Reason(id=candidate_id, reason=reason, talking_point=talk))

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
IMPLIED_USERS_RE = re.compile(r"\b(?:до|от|up\s+to|from|of|for)\s+(\d+)", re.I)
# Unit word BEFORE the number: "количество пользователей — 5", "users: 5",
# "лимит пользователей составляет 5" (MCP run 20260929-215908: x06 came out
# unit=bare because «составляет» sat between the unit word and the number).
USERS_AFTER_RE = re.compile(
    rf"(?:пользовател\w*|сотрудник\w*|человек\w*|user\w*|seat\w*|мест(?:а|ов)?)"
    rf"\s*(?:[—–-]|:|is|=|составля\w*|равен|равно|может\s+быть)?\s*({_NUM})",
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
    _, inapplicable = inapplicable_plans(customer_message)
    skipped = {entry.id for entry in inapplicable}
    for match in matches:
        if match.entry.id in skipped:
            # The customer asked for more users than this plan supports: its
            # price/limit must not license a claim in the reply (ru21 bug —
            # a "Business for 10 employees" answer quoting Start's 990 ₽).
            continue
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


# Trailing letter sign-offs the model invents on retries ("С уважением,
# [Your Name]", "Best regards, [Your Company Name]", a bare [Имя_Менеджера]
# last line) — MCP run 20260929-210550: retries that were otherwise clean
# failed only on these. Deterministic cleanup, not a rewrite: everything
# from the sign-off keyword to the end is dropped, as is a final line that
# is only a bracketed placeholder.
_SIGNOFF_RE = re.compile(
    r"\s*\n?\s*(?:с\s+уважением|с\s+наилучшими\s+пожеланиями"
    r"|с\s+лучшими\s+пожеланиями|best\s+regards|kind\s+regards"
    r"|with\s+regards|warm\s+regards|sincerely)\b[\s\S]*$",
    re.I,
)
_BRACKET_SPAN_RE = re.compile(r"[ \t]?\[[^\[\]\n]{1,60}\]")


def strip_signoff(text: str) -> str:
    """Drop a trailing letter sign-off and any bracketed placeholder span.

    Square brackets are never legitimate in a customer reply (kb_refs live in
    a separate field), so an inline «[Имя_Менеджера]» — which also failed
    script_ok via its underscore — is removed wholesale (run 20260929-213144,
    ru21 attempt 1).
    """
    out = _SIGNOFF_RE.sub("", text)
    out = _BRACKET_SPAN_RE.sub("", out)
    out = re.sub(r"[ \t]+([.!?])", r"\1", out)
    return out.strip()


_SENT_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def strip_foreign_percent_sentences(
    reply: str,
    *,
    matches: Sequence[Match],
    deal: DealContext,
    customer_message: str,
) -> str:
    """Drop whole sentences that echo a percent outside the allowlist.

    The model refuses injections by REPEATING the forbidden percentage
    («скидка администратора 90% не входит…», "we do not include a 100%
    discount", "we can't match a 40% discount") — runs 20260929-213144 and
    215908 failed numbers_ok on that echo in both attempts. The refusing
    sentence goes; the rest of the reply — including the real 20% — stays.
    Same class as strip_percent_denial: deterministic cleanup, no rewrite.
    """
    allowed = allowed_numbers(matches, deal, customer_message)
    allowed_pcts = allowed.get("percent", set())
    sentences = _SENT_BOUNDARY_RE.split(reply)
    kept: list[str] = []
    dropped = False
    for sent in sentences:
        pcts = [c for c in extract_claims(sent) if c.unit == "percent"]
        if pcts and any(c.value not in allowed_pcts for c in pcts):
            dropped = True
            continue
        kept.append(sent)
    out = " ".join(kept).strip()
    # What survives a strip must still be a real answer: «Конечно!» left over
    # from «Конечно! Скидка 90% действует…» would agree to the injection.
    if dropped and len(out) < 25:
        return ""
    return out


# ---------------------------------------------------------------------------
# Plan-capacity guardrail (context-aware numeric check).
#
# Real failure this fixes: "тарфи для 10 сотрудников" → a reply recommending
# «Бизнес» while quoting Start's 990 ₽ (run 20260929-155851, ru21_typo_tarfy).
#
# A plan whose facts.max_users is below the user count the customer explicitly
# asked for must not be presented as the applicable plan:
#   1. allowed_numbers() drops that plan's facts so check_numbers rejects its
#      price/limits (the ru21 case);
#   2. check_plan_capacity() rejects a reply that names the plan as the answer,
#      unless the reply explains that the plan does NOT fit (negation cues).
#
# Only typed users-claims in the CUSTOMER's own message create the constraint
# ("тариф для 10 сотрудников"); deal seats and numbers inside the reply never
# do. A message without such a claim ("How much is Start?") constrains nothing.
# Plans without max_users in facts (e.g. Enterprise, "50+") are never blocked.
# ---------------------------------------------------------------------------

_PLAN_CONTEXT_TOKENS = frozenset(
    tokenize("тариф тарифы план планы подписка subscription plan plans tariff")
)
# Phrases that explain a limit instead of presenting the plan as suitable.
_NEGATION_CUES = (
    "не подходит",
    "не подойд",
    "не влез",
    "не хватит",
    "не рассчитан",
    "не позволит",
    "максимум",
    "does not fit",
    "doesn't fit",
    "not fit",
    "not suitable",
    "won't fit",
    "will not fit",
    "too small",
    "not enough",
    "cannot fit",
    "can't fit",
    "maximum",
)


def requested_capacity(customer_message: str) -> float | None:
    """The largest user count the customer explicitly wrote, if any."""
    users = [c.value for c in extract_claims(customer_message) if c.unit == "users"]
    return max(users) if users else None


def inapplicable_plans(customer_message: str) -> tuple[float | None, list[KbEntry]]:
    """(capacity, plan entries whose max_users < capacity). Empty if no claim."""
    capacity = requested_capacity(customer_message)
    if capacity is None:
        return None, []
    bad = []
    for entry in get_kb():
        if entry.type != "plan":
            continue
        max_users = entry.facts.get("max_users")
        if isinstance(max_users, int | float) and max_users < capacity:
            bad.append(entry)
    return capacity, bad


def check_plan_capacity(reply: str, customer_message: str) -> list[str]:
    """capacity_ok: an under-sized plan must not be offered as the answer.

    The reply must both name a plan (a plan-context word like «тариф»/«plan»)
    and one of the inapplicable plan's distinctive title tokens; replies that
    explain the limit instead (negation cue anywhere, replies that never name
    a plan, e.g. "let's get started") pass.
    """
    capacity, entries = inapplicable_plans(customer_message)
    if not entries:
        return []
    reply_tokens = set(tokenize(reply))
    if not (_PLAN_CONTEXT_TOKENS & reply_tokens):
        return []
    low = reply.lower()
    if any(cue in low for cue in _NEGATION_CUES):
        return []
    problems: list[str] = []
    for entry in entries:
        title_tokens = set(tokenize(f"{entry.title.ru} {entry.title.en}")) - _PLAN_CONTEXT_TOKENS
        if title_tokens & reply_tokens:
            problems.append(
                f"plan_capacity_ok failed: «{entry.title.ru}» supports "
                f"{entry.facts.get('max_users')} users but the customer asked for "
                f"{capacity:g} — never present this plan as suitable; recommend a "
                "plan that fits or explain the limit safely"
            )
    return problems


# ---------------------------------------------------------------------------
# Script whitelist, meta markers and the manager-role rule (run 20260929-175559)
#
# - ru31 / x13: replies contained Chinese text and template artifacts
#   ("——客户回复部分——") because language_ok only compares ru/en — any script
#   that is neither Cyrillic nor Latin still "looks Russian" to it.
# - ru01 / ru22 / x06: the reply is written BY the manager in the chat, yet it
#   told the customer to contact/ask the manager — a role confusion the model
#   made because the prompt says it helps "a manager".
# The whitelist accepts exactly what this product's KB, replies and hint
# fields may contain: Cyrillic, Latin, digits, whitespace, common punctuation
# and the ruble sign. Anything else (CJK, fullwidth forms, emoji, markup) is
# rejected and retried once before the templated fallback.
# ---------------------------------------------------------------------------

_DISALLOWED_SCRIPT_RE = re.compile(
    r"[^A-Za-zЀ-ӿ0-9\s«»„“”'‘’–—…₽%№()[\]/:;,.!?+=-]"
)

# Strings that only ever belong to model scaffolding or internal fields;
# they must never appear in customer text OR in the manager-facing hints.
META_MARKERS = (
    "——",
    "客户",
    "part 1",
    "part 2",
    "customer_reply",
    "internal",
    "<kb>",
    "```",
)


def check_script(text: str) -> list[str]:
    """script_ok: only the allowed script/punctuation set may appear."""
    hit = _DISALLOWED_SCRIPT_RE.search(text)
    if hit is None:
        return []
    ch = hit.group(0)
    return [f"script_ok failed: disallowed character {ch!r} (U+{ord(ch):04X})"]


def check_meta_markers(text: str) -> list[str]:
    low = text.casefold()
    return [f"meta marker in text: {marker!r}" for marker in META_MARKERS if marker in low]


def check_output_script(output: LlmOutput) -> list[str]:
    """script_ok over the reply AND every internal reason/talking point."""
    problems: list[str] = []
    texts = [output.customer_reply]
    for reason in output.upsell_reasons + output.cross_sell_reasons:
        texts.extend((reason.reason, reason.talking_point))
    for text in texts:
        problems += check_script(text)
        problems += check_meta_markers(text)
    return problems


# Verbs that route the customer to somebody else. The reply itself is written
# by the manager, so telling the customer to go ask a manager is a role
# violation (and a dead end for the customer).
_REFERRAL_PATTERNS = (
    r"обратитесь к (?:нашему|вашему)?\s*менеджер",
    r"обратиться к (?:нашему|вашему)?\s*менеджер",
    r"свяжитесь с (?:наш|ваш)им\s+менеджер",
    r"связаться с (?:наш|ваш)им\s+менеджер",
    r"уточните у (?:менеджер|нашего|вашего)",
    r"уточнить у (?:менеджер|нашего|вашего)",
    r"уточняйте у (?:менеджер|нашего|вашего)",
    r"спросите у (?:менеджер|нашего|вашего)",
    r"спросить у (?:менеджер|нашего|вашего)",
    r"уточните у менеджер",
    r"у вашего менеджера",
    r"у нашего менеджера",
    r"у менеджера",
    r"у менеджеру",
    r"к менеджеру",
    r"к нашему менеджеру",
    r"к вашему менеджеру",
    r"с нашим менеджером",
    r"с вашим менеджером",
    r"с менеджером",
    r"напишите менеджер",
    r"написать менеджер",
    r"детали у менеджер",
    r"подробности у менеджер",
    r"contact (?:our|your|the) manager",
    r"ask (?:your|our|the) manager",
    r"speak (?:to|with) (?:our|your|the) manager",
    r"talk (?:to|with) (?:our|your|the) manager",
    r"reach out to (?:our|your|the) manager",
    r"check with (?:our|your|the) manager",
    r"clarify with (?:our|your|the) manager",
    r"details from (?:our|your|the) manager",
)
_REFERRAL_RE = re.compile("|".join(f"(?:{p})" for p in _REFERRAL_PATTERNS), re.I)


def check_manager_referral(reply: str) -> list[str]:
    """role_ok: the reply IS the manager's message — never route the customer
    to "the manager". Legit mentions survive: "будет подтверждена менеджером",
    "персональный менеджер", "confirmed by the manager" (none match above).
    """
    hit = _REFERRAL_RE.search(reply)
    if hit is None:
        return []
    return [
        f"role_ok failed: the reply is written BY the manager, so it must not send "
        f"the customer to a manager — remove the referral ({hit.group(0)!r})"
    ]


# ---------------------------------------------------------------------------
# Language, leakage and length checks (CONTEXT §17, validators 3/9)
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

# Template scaffolding the model occasionally hallucinates into a reply
# (run 20260929-155851: one reply ended with the sign-off "[Your Company
# Name]"). No legitimate sentence in this product uses brackets, braces or
# angle brackets, so any hit is a placeholder and fails no_leakage.
_PLACEHOLDER_PATTERNS = (
    ("bracketed placeholder", re.compile(r"\[[^\[\]\n]{1,60}\]")),
    ("template variable", re.compile(r"\{[^{}\n]{1,40}\}")),
    ("markup placeholder", re.compile(r"<[^\W\d_][^<>\n]{0,60}>")),
)
_PLACEHOLDER_WORDS = ("lorem ipsum",)


def check_language(reply: str, customer_lang: str) -> bool:
    """language_ok: detected reply language == customer language.

    An inconclusive detection (too short / ambiguous — detect_text_lang
    returns None, e.g. «Спасибо!») cannot prove a mismatch, so it passes;
    a confidently detected wrong language still fails.
    """
    detected = detect_text_lang(reply)
    return detected is None or detected == customer_lang


def check_length(reply: str) -> bool:
    """length_ok: reply present and ≤ 450 characters (3–4 short sentences)."""
    return 0 < len(reply) <= MAX_REPLY_CHARS


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _title_token_groups(entry: KbEntry) -> list[frozenset[str]]:
    """Distinctive title tokens per language («тариф»/«plan» are context)."""
    groups: list[frozenset[str]] = []
    for title in (entry.title.ru, entry.title.en):
        tokens = frozenset(tokenize(title)) - _PLAN_CONTEXT_TOKENS
        if tokens:
            groups.append(tokens)
    return groups


# Sentence boundaries for cue matching («перейти на тариф…», "consider the …").
_SENT_SPLIT = re.compile(r"[.!?;\n]+")

# Upgrade-offer wording: the reply must never try to sell a different tier.
_PITCH_CUES = (
    "перейти",
    "переход",
    "переключ",
    "рассмотр",
    "рекоменду",
    "советуем",
    "переезд",
    "upgrade",
    "consider",
    "we recommend",
    "switch to",
    "move to",
    "take a look",
)

# «business days» tokenizes to {busi, day} — the same stem as the EN title of
# plan-business ("Business plan" → {busi}). Normalise it away before scanning.
_BUSINESS_DAYS_RE = re.compile(r"\bbusiness\s+days?\b", re.IGNORECASE)

# Boilerplate words that appear in every KB text; subtracted so an add-on's
# "distinctive content" really is distinctive («отчёты по менеджерам» — yes,
# «в месяц» / «тариф» — no).
_GENERIC_CONTENT = frozenset(
    tokenize(
        "тариф тарифы тарифе тарифа план планы месяцы месяц месяца цена цены "
        "стоимость рублей рубля рублей руб ру rub ruble rubles пользователь "
        "пользователи пользователя пользователей user users аккаунт аккаунта "
        "account accounts доступен доступна доступно доступны входит включает "
        "включены включено включены выше бесплатно free сервис сервиса "
        "команда команды team features feature plan plans month months "
        "price cost available above will"
    )
)


def _addon_content_tokens(entry: KbEntry) -> frozenset[str]:
    """Distinctive stemmed tokens of an add-on's text (minus title/generic)."""
    text_tokens = set(tokenize(entry.text.ru + " " + entry.text.en))
    title_tokens = set(tokenize(entry.title.ru + " " + entry.title.en))
    return frozenset(text_tokens - title_tokens - _GENERIC_CONTENT)


def unallowed_plan_mentions(
    reply: str,
    *,
    message: str,
    matches: Sequence[Match],
    threshold: float,
    deal_plan: str | None = None,
) -> list[str]:
    """Plan/add-on titles in the reply — block the defects, not the facts.

    Allowed context (nothing to check):
    (a) the customer's own message contains a distinctive title token,
    (b) the entity is a retrieved match with score >= threshold,
    (c) it is the customer's current plan (deal plan).

    Without context arguments there is nothing to evaluate the rule
    against, so it returns [] (callers in the app always pass context).

    Otherwise the title may still appear in a factual sentence — MCP run
    20260929-193543 showed the model quoting KB tier-scope facts ("доступно
    на тарифе «Бизнес» и выше", "включены все функции тарифа «Бизнес»") and
    falling back to a template every time such a mention was blocked. So
    only two shapes are problems:

    1. Upgrade pitch: the same sentence offers another plan («перейти на
       тариф…», "consider the … plan") — upsells belong to PART 2 hints.
    2. Add-on content attributed to a plan: the reply describes a retrieved
       add-on's content ("отчёты по менеджерам") under a plan title while
       never naming the add-on itself (the ru18 wrong-fact defect).

    A bare mention with neither shape is allowed (conservative default for
    factual prose; numbers_guard and the prompt still apply).
    """
    if not matches and not message and not deal_plan:
        return []
    # «business days» must not read as the Business plan title (en12).
    scan = _BUSINESS_DAYS_RE.sub("workdays", reply)
    reply_tokens = set(tokenize(scan))
    message_tokens = set(tokenize(message))
    allowed_ids = {m.entry.id for m in matches if m.score >= threshold}
    if deal_plan and deal_plan != "none":
        allowed_ids.add(f"plan-{deal_plan}")

    retrieved_addons = [m.entry for m in matches if m.entry.type == "addon"]

    problems: list[str] = []
    for entry in get_kb():
        if entry.type not in ("plan", "addon") or entry.id in allowed_ids:
            continue
        groups = _title_token_groups(entry)
        if not any(group <= reply_tokens for group in groups):
            continue
        if any(group & message_tokens for group in groups):
            continue

        # (2) add-on content attributed to this entry without naming the add-on
        attributing: KbEntry | None = None
        for addon in retrieved_addons:
            if addon.id == entry.id:
                continue
            addon_groups = _title_token_groups(addon)
            if any(g <= reply_tokens for g in addon_groups):
                continue  # the add-on itself is named — not an attribution
            content = _addon_content_tokens(addon)
            if len(content & reply_tokens) >= 2:
                attributing = addon
                break
        if attributing is not None:
            problems.append(
                f"add-on content attributed to plan/add-on without naming the "
                f"add-on: {entry.id} «{entry.title.ru}» — name "
                f"«{attributing.title.ru}» explicitly or keep the add-on out "
                "of this reply"
            )
            continue

        # (1) upgrade pitch in the same sentence
        pitch = False
        for sentence in _SENT_SPLIT.split(scan):
            if not sentence.strip():
                continue
            if not any(group <= set(tokenize(sentence)) for group in groups):
                continue
            low = sentence.lower()
            if any(cue in low for cue in _PITCH_CUES):
                pitch = True
                break
        if pitch:
            problems.append(
                f"upgrade pitch in customer_reply: {entry.id} «{entry.title.ru}» — "
                "never offer another plan or add-on in the reply (PART 2 only)"
            )
    return problems


def check_leakage(
    output: LlmOutput,
    candidates: Candidates,
    *,
    message: str = "",
    matches: Sequence[Match] = (),
    threshold: float | None = None,
    deal_plan: str | None = None,
) -> list[str]:
    """no_leakage: internal text must never appear inside customer_reply.

    Also enforces the plan/add-on title rule (STEP 4); that part runs only
    when context is supplied (message/matches/threshold/deal_plan from the
    app).
    """
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

    for name, pattern in _PLACEHOLDER_PATTERNS:
        hit = pattern.search(output.customer_reply)
        if hit:
            problems.append(f"placeholder in reply ({name}): {hit.group(0)!r}")
    for word in _PLACEHOLDER_WORDS:
        if word in low:
            problems.append(f"placeholder in reply: {word!r}")

    if threshold is not None:
        problems += unallowed_plan_mentions(
            output.customer_reply,
            message=message,
            matches=matches,
            threshold=threshold,
            deal_plan=deal_plan,
        )

    return problems
