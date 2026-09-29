"""RU/EN tokenizer with Snowball stemming (CONTEXT §16)."""

import re
import string

import snowballstemmer

RU_STOPWORDS = frozenset(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
    только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли
    если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
    ничего ей они тут где есть надо ней для мы тебя их чем была сам чтоб без будто
    чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним
    здесь этом один почти мой тем чтобы нее сейчас были куда зачем сказать всех
    никогда сегодня при наконец два об другой хоть после над больше тот через эти
    нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед
    иногда лучше чуть том нельзя такой им более всегда конечно всю между это
    """.split()
)

EN_STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been
    before being below between both by can could did do does doing down during each
    few for from further had has have having he her here hers herself him himself
    his how i if in into is it its itself just me more most my myself no nor not now
    of off on once only or other our ours ourselves out over own same she should so
    some such than that the their theirs them themselves then there these they this
    those through to too under until up very was we were what when where which while
    who whom why will with would you your yours yourself yourselves also
    """.split()
)

# Brand/tech tokens are excluded from language detection and kept as-is in tokens
# so "Подключите Telegram" stays Russian (CONTEXT §4a).
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

_PUNCT_TABLE = str.maketrans("", "", string.punctuation + "«»„“”…—–·")
# Normalise "1с" ↔ "1c": Cyrillic "с" directly next to a digit becomes Latin "c".
_CYRILLIC_C_RE = re.compile(r"(?<=\d)с|с(?=\d)")

_russian_stemmer = snowballstemmer.stemmer("russian")
_english_stemmer = snowballstemmer.stemmer("english")


def _is_cyrillic(token: str) -> bool:
    return any("а" <= ch <= "я" or ch == "ё" for ch in token)


def tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, drop stopwords, stem per script.

    Latin/Cyrillic "с" in tokens like "1с" is normalised to "1c".
    Numeric tokens are kept (prices, seat counts).
    """
    text = text.lower().translate(_PUNCT_TABLE)
    tokens: list[str] = []
    for raw in text.split():
        token = _CYRILLIC_C_RE.sub("c", raw)
        if not token or token in RU_STOPWORDS or token in EN_STOPWORDS:
            continue
        if _is_cyrillic(token):
            tokens.append(_russian_stemmer.stemWord(token))
        elif token.isalpha() or any(ch.isalpha() for ch in token):
            tokens.append(_english_stemmer.stemWord(token))
        else:
            tokens.append(token)
    return tokens
