"""Retrieval-layer contracts shared by dense, sparse, hybrid, and rerank steps."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_ladder.rag.indexing.index_record import IndexRecord


class RetrievalQuery(BaseModel):
    text: str
    tokens: list[str] = Field(default_factory=list)
    dense_vector: list[float] | None = None


class RetrievalResult(BaseModel):
    record: IndexRecord
    score: float
    rank: int
    retriever: Literal["dense", "bm25", "hybrid", "rerank"]
    details: dict[str, float | int | str] = Field(default_factory=dict)


class HybridSearchResult(BaseModel):
    record: IndexRecord
    score: float
    rank: int
    dense_score: float | None = None
    sparse_score: float | None = None
    dense_rank: int | None = None
    sparse_rank: int | None = None


class RerankedChunk(BaseModel):
    record: IndexRecord
    score: float
    rank: int
    hybrid_score: float
    bonuses: dict[str, float] = Field(default_factory=dict)
