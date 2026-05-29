"""Structured v0.2 RAG answer frame."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_ladder.rag.contracts.route import RouteName
from agent_ladder.rag.contracts.source import Citation, SourceCard


class AnswerFrameV1(BaseModel):
    answer: str
    route: RouteName
    sources: list[SourceCard] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    used_chunks: list[str] = Field(default_factory=list)
    run_log: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
