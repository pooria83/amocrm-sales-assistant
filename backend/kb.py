import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

KB_PATH = Path(__file__).resolve().parent.parent / "kb" / "kb.json"

ID_PATTERN = re.compile(r"^[a-z0-9-]+$")

# A `facts` key must carry its unit in the key name so the numeric guardrail
# can build typed (value, unit) allowlists (CONTEXT §4a / §3 principle 4).
UNIT_TOKENS = ("rub", "percent", "users", "days", "hours")


class KbError(Exception):
    """Raised when kb/kb.json is structurally invalid."""


class BilingualText(BaseModel):
    ru: str = Field(min_length=1)
    en: str = Field(min_length=1)


class BilingualKeywords(BaseModel):
    ru: list[str] = Field(min_length=1)
    en: list[str] = Field(min_length=1)


class KbEntry(BaseModel):
    id: str
    type: Literal["plan", "limit", "integration", "addon", "objection", "faq"]
    title: BilingualText
    text: BilingualText
    keywords: BilingualKeywords
    facts: dict[str, float] = Field(default_factory=dict)
    upsell_to: list[str] = Field(default_factory=list)
    cross_sell: list[str] = Field(default_factory=list)
    requires: str | None = None
    trigger_hints: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def id_is_slug(cls, v: str) -> str:
        if not ID_PATTERN.match(v):
            raise ValueError(f"id must be lowercase slug: {v!r}")
        return v

    @field_validator("facts")
    @classmethod
    def facts_keys_carry_units(cls, v: dict[str, float]) -> dict[str, float]:
        for key in v:
            if not any(token in key for token in UNIT_TOKENS):
                raise ValueError(
                    f"facts key {key!r} must carry its unit in the name "
                    f"(one of {', '.join(UNIT_TOKENS)})"
                )
        return v


def load_kb(path: Path | None = None) -> list[KbEntry]:
    """Load and validate kb/kb.json.

    Raises KbError on any structural problem (bad ids, missing bilingual fields,
    unit-less fact keys, unknown relation targets, duplicate ids).
    """
    kb_path = path or KB_PATH
    if not kb_path.exists():
        raise KbError(f"KB file not found: {kb_path}")
    try:
        raw = json.loads(kb_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KbError(f"invalid JSON in {kb_path}: {exc}") from exc

    try:
        entries = [KbEntry.model_validate(item) for item in raw["entries"]]
    except (KeyError, ValidationError) as exc:
        raise KbError(f"invalid KB in {kb_path}: {exc}") from exc

    ids = [e.id for e in entries]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise KbError(f"duplicate KB ids: {dupes}")

    known = set(ids)
    for entry in entries:
        for relation in entry.upsell_to + entry.cross_sell:
            if relation not in known:
                raise KbError(f"{entry.id}: unknown relation target {relation!r}")
        if entry.requires is not None and entry.requires not in known:
            raise KbError(f"{entry.id}: unknown requires target {entry.requires!r}")

    return entries


@lru_cache(maxsize=1)
def get_kb() -> tuple[KbEntry, ...]:
    return tuple(load_kb())


def get_entry(entry_id: str) -> KbEntry | None:
    for entry in get_kb():
        if entry.id == entry_id:
            return entry
    return None
