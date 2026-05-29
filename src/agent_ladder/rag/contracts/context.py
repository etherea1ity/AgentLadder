"""Context contracts for what the Writer receives."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_ladder.rag.contracts.retrieval import RerankedChunk


class BuiltContext(BaseModel):
    query: str
    selected_chunks: list[RerankedChunk]
    context_text: str
    token_estimate: int
    source_summaries: list[dict[str, str | int | float | None]] = Field(default_factory=list)
