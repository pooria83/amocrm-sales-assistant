"""Pydantic request/response models (API contract, CONTEXT §13)."""

from typing import Literal

from pydantic import BaseModel, Field

Lang = Literal["ru", "en"]
LangSource = Literal["message", "conversation", "ui_default"]


class HistoryMessage(BaseModel):
    role: Literal["customer", "manager"]
    text: str


class RetrieveRequest(BaseModel):
    message: str = Field(min_length=1)
    ui_lang: Lang = "ru"
    history: list[HistoryMessage] = Field(default_factory=list)


class MatchOut(BaseModel):
    id: str
    title: str
    score: float
    matched_terms: list[str]


class RetrieveResponse(BaseModel):
    detected_lang: Lang
    lang_source: LangSource
    matches: list[MatchOut]
    threshold: float
    grounded: bool
