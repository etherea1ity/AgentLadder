"""Hybrid score fusion for dense and sparse retrieval results."""

from __future__ import annotations

from agent_ladder.rag.contracts.retrieval import HybridSearchResult
from agent_ladder.rag.retrieval.bm25 import BM25SearchResult
from agent_ladder.rag.retrieval.dense import DenseRetrievalResult


class HybridRetriever:
    def __init__(self, *, dense_weight: float = 0.7, sparse_weight: float = 0.3) -> None:
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight

    def fuse(
        self,
        *,
        dense_results: list[DenseRetrievalResult],
        sparse_results: list[BM25SearchResult],
        top_k: int = 8,
    ) -> list[HybridSearchResult]:
        dense_norm = _normalize({item.record.record_id: item.score for item in dense_results})
        sparse_norm = _normalize({item.record.record_id: item.score for item in sparse_results})
        records = {item.record.record_id: item.record for item in dense_results}
        records.update({item.record.record_id: item.record for item in sparse_results})
        dense_rank = {item.record.record_id: item.rank for item in dense_results}
        sparse_rank = {item.record.record_id: item.rank for item in sparse_results}
        dense_raw = {item.record.record_id: item.score for item in dense_results}
        sparse_raw = {item.record.record_id: item.score for item in sparse_results}

        fused: list[HybridSearchResult] = []
        for record_id, record in records.items():
            score = self.dense_weight * dense_norm.get(record_id, 0.0) + self.sparse_weight * sparse_norm.get(record_id, 0.0)
            fused.append(
                HybridSearchResult(
                    record=record,
                    score=score,
                    rank=0,
                    dense_score=dense_raw.get(record_id),
                    sparse_score=sparse_raw.get(record_id),
                    dense_rank=dense_rank.get(record_id),
                    sparse_rank=sparse_rank.get(record_id),
                )
            )
        fused.sort(key=lambda item: item.score, reverse=True)
        return [item.model_copy(update={"rank": index + 1}) for index, item in enumerate(fused[:top_k])]


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return {key: 1.0 for key in scores}
    return {key: (value - minimum) / (maximum - minimum) for key, value in scores.items()}
