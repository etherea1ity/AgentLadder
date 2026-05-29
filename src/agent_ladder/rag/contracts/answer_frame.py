"""Structured v0.2 RAG writer and answer frames."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EvidenceItem(BaseModel):
    """One selected evidence block that can safely be shown to the writer/UI."""

    rank: int
    title: str | None = None
    text: str
    score: float | None = None
    concept: str | None = None


class WriterInputFrame(BaseModel):
    """The minimal RAG input contract for the writer LLM."""

    question: str
    evidence: list[EvidenceItem] = Field(default_factory=list)


class AnswerFrameV1(BaseModel):
    """The final answer plus the evidence it was grounded in.

    Runtime metadata such as route, token usage, and run ids belongs in RunLog
    or module traces, not in the answer frame itself.
    """

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
