"""Explainable reranker for v0.2 RAG."""

from __future__ import annotations

from agent_ladder.rag.contracts.retrieval import HybridSearchResult, RerankedChunk
from agent_ladder.rag.retrieval.tokenizer import tokenize


class SimpleReranker:
    def rerank(self, query: str, candidates: list[HybridSearchResult], top_k: int = 4) -> list[RerankedChunk]:
        query_tokens = set(tokenize(query))
        reranked: list[RerankedChunk] = []
        for candidate in candidates:
            record = candidate.record
            metadata_text = " ".join(
                part
                for part in [
                    record.metadata.title,
                    record.metadata.summary,
                    record.metadata.chapter,
                    " ".join(record.metadata.tags),
                ]
                if part
            )
            record_tokens = set(tokenize(record.text))
            metadata_tokens = set(tokenize(metadata_text))
            exact_matches = query_tokens & record_tokens
            metadata_matches = query_tokens & metadata_tokens
            bonuses = {
                "exact_keyword_bonus": min(0.18, 0.03 * len(exact_matches)),
                "metadata_match_bonus": min(0.12, 0.04 * len(metadata_matches)),
                "chapter_alias_bonus": _chapter_alias_bonus(query, record.metadata.chapter),
            }
            score = candidate.score + sum(bonuses.values())
            reranked.append(RerankedChunk(record=record, score=score, rank=0, hybrid_score=candidate.score, bonuses=bonuses))
        reranked.sort(key=lambda item: item.score, reverse=True)
        return [item.model_copy(update={"rank": index + 1}) for index, item in enumerate(reranked[:top_k])]


def _chapter_alias_bonus(query: str, chapter: str | None) -> float:
    normalized = query.lower()
    if not chapter:
        return 0.0
    chapter_key = chapter.lower()
    aliases = {
        "ch01": ["chapter one", "first chapter", "chapter 1", "ch01", "v0.1"],
        "ch02": ["chapter two", "second chapter", "chapter 2", "ch02", "v0.2"],
    }
    return 1.2 if any(alias in normalized for alias in aliases.get(chapter_key, [])) else 0.0
