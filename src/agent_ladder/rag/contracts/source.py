"""Source and citation contracts for v0.2 RAG answers."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceCard(BaseModel):
    source_id: str
    title: str
    source_path: str
    chapter: str | None = None
    version: str | None = None
    summary: str | None = None
    used_chunk_ids: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    citation_id: str
    source_id: str
    chunk_id: str
    label: str
    quote_or_summary: str
