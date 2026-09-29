"""Language detection with conversation fallback (CONTEXT §4a).

Script ratio on the message itself; very short or ambiguous messages inherit
the language of the conversation, falling back to the UI language.
"""

from collections.abc import Iterable

# Brand/tech tokens are ignored when counting letters, so "Подключите Telegram"
# stays Russian. (CONTEXT §4a)
BRAND_TOKENS = frozenset(
    {
        "telegram",
        "whatsapp",
        "1c",
        "crm",
        "google",
        "gsheets",
        "api",
        "sso",
        "sla",
        "ios",
        "android",
        "rest",
        "teamflow",
        "ok",
    }
)

MIN_LETTERS = 8  # fewer letters than this ⇒ ambiguous (e.g. "Price?", "10")

LANG_MESSAGE = "message"
LANG_CONVERSATION = "conversation"
LANG_UI_DEFAULT = "ui_default"


def _is_cyrillic(ch: str) -> bool:
    return "а" <= ch <= "я" or ch == "ё"


def _is_latin(ch: str) -> bool:
    return "a" <= ch <= "z"


def detect_text_lang(text: str) -> str | None:
    """ru / en by script ratio, or None when the text is ambiguous.

    Known failure mode (documented in README): transliterated Russian in
    Latin script ("skolko stoit") is detected as English.
    """
    words = text.lower().split()
    content_words = [w for w in words if w.strip(".,!?;:()«»\"'") not in BRAND_TOKENS]
    joined = " ".join(content_words)
    cyr = sum(1 for ch in joined if _is_cyrillic(ch))
    lat = sum(1 for ch in joined if _is_latin(ch))
    if cyr + lat < MIN_LETTERS:
        return None
    if cyr > lat:
        return "ru"
    if lat > cyr:
        return "en"
    return None


def _customer_history_langs(history: Iterable[dict]) -> list[str]:
    langs: list[str] = []
    for msg in history:
        if msg.get("role") == "customer":
            lang = detect_text_lang(str(msg.get("text", "")))
            if lang:
                langs.append(lang)
    return langs


def detect_language(
    message: str,
    history: Iterable[dict] | None = None,
    ui_lang: str = "ru",
) -> tuple[str, str]:
    """Returns (lang, lang_source) per §13: message | conversation | ui_default."""
    lang = detect_text_lang(message)
    if lang:
        return lang, LANG_MESSAGE

    customer_langs = _customer_history_langs(history or [])
    if customer_langs:
        return customer_langs[-1], LANG_CONVERSATION

    return ui_lang, LANG_UI_DEFAULT
