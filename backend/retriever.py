"""RU/EN tokenizer with Snowball stemming and BM25 retrieval (CONTEXT §16)."""

import os
import re
import string
from dataclasses import dataclass
from functools import lru_cache

import snowballstemmer
from rank_bm25 import BM25Okapi

from backend.kb import KbEntry, get_kb

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


DEFAULT_K1 = 1.5
DEFAULT_B = 0.75
DEFAULT_TOP_K = 3
DEFAULT_THRESHOLD = 3.0


def get_threshold() -> float:
    """Grounding threshold; calibrated on eval/cases.yaml (CONTEXT §16)."""
    return float(os.getenv("RETRIEVAL_THRESHOLD", str(DEFAULT_THRESHOLD)))


def index_text(entry: KbEntry) -> str:
    """Both languages are indexed so an EN query can match RU content and vice versa.

    Titles are counted twice so the entry name outweighs body-word overlap
    (e.g. a question about "the Start plan" should rank plan-start above
    limit-seats, which shares the same generic words).
    """
    title = f"{entry.title.ru} {entry.title.en}"
    parts = [title, title, entry.text.ru, entry.text.en]
    parts += entry.keywords.ru + entry.keywords.en
    return " ".join(parts)


@dataclass(frozen=True)
class Match:
    entry: KbEntry
    score: float
    matched_terms: list[str]


class Retriever:
    """Single retrieval service shared by /api/retrieve and /api/assist (CONTEXT §4a)."""

    def __init__(self, entries: tuple[KbEntry, ...]):
        self.entries = entries
        self._docs = [tokenize(index_text(e)) for e in entries]
        self._bm25 = BM25Okapi(self._docs, k1=DEFAULT_K1, b=DEFAULT_B)

    def search(self, message: str, top_k: int = DEFAULT_TOP_K) -> list[Match]:
        query_tokens = tokenize(message)
        if not query_tokens or not self.entries:
            return []
        scores = self._bm25.get_scores(query_tokens)
        ranked = sorted(
            ((i, float(s)) for i, s in enumerate(scores) if s > 0),
            key=lambda pair: pair[1],
            reverse=True,
        )[:top_k]

        matches: list[Match] = []
        for index, score in ranked:
            doc_tokens = self._docs[index]
            seen: list[str] = []
            for token in query_tokens:
                if token in doc_tokens and token not in seen:
                    seen.append(token)
            matches.append(Match(entry=self.entries[index], score=round(score, 2), matched_terms=seen[:8]))
        return matches

    def retrieve(self, message: str, top_k: int = DEFAULT_TOP_K) -> tuple[list[Match], float, bool]:
        """Returns (matches, threshold, grounded). Grounded iff top score ≥ threshold."""
        threshold = get_threshold()
        matches = self.search(message, top_k=top_k)
        grounded = bool(matches) and matches[0].score >= threshold
        return matches, threshold, grounded


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    return Retriever(get_kb())
