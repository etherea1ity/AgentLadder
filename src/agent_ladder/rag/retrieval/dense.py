"""Dense retrieval wrapper around the chapter's simple vector index."""

from __future__ import annotations

from pydantic import BaseModel

from agent_ladder.rag.indexing.index_record import IndexRecord
from agent_ladder.rag.indexing.simple_vector_index import SimpleVectorIndex


class DenseRetrievalResult(BaseModel):
    record: IndexRecord
    score: float
    rank: int
    score_type: str = "dense_cosine"


class DenseRetriever:
    def __init__(self, records: list[IndexRecord]) -> None:
        self.index = SimpleVectorIndex(records)

    def search(self, query_vector: list[float], top_k: int = 5) -> list[DenseRetrievalResult]:
        results = self.index.search(query_vector=query_vector, top_k=top_k)
        return [DenseRetrievalResult(record=item.record, score=item.score, rank=index + 1) for index, item in enumerate(results)]
