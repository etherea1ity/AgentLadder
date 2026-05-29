"""Routing contracts for deciding whether Klara needs RAG."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


RouteName = Literal["direct", "rag"]
QueryType = Literal[
    "general_chat",
    "project_knowledge",
    "chapter_question",
    "technical_question",
    "ambiguous",
]


class RouterInput(BaseModel):
    """Structured JSON input for the intent router module."""

    question: str

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("question must not be empty")
        return text


class RouteDecision(BaseModel):
    """Structured JSON output from the intent router module."""

    route: RouteName
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_local_knowledge: bool
    query_type: QueryType = "ambiguous"
    rewritten_query: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    router_model: str | None = None
    fallback_used: bool = False

    @field_validator("reason")
    @classmethod
    def reason_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("reason must not be empty")
        return text

    @field_validator("rewritten_query")
    @classmethod
    def normalize_rewritten_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None
