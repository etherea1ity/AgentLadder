"""Brute-force dense vector search for Klara's small teaching library."""

from pydantic import BaseModel

from agent_ladder.rag.indexing.index_record import IndexRecord
from agent_ladder.rag.indexing.similarity import cosine_similarity


class DenseSearchResult(BaseModel):
    """One result from dense vector search."""

    record: IndexRecord
    score: float
    score_type: str = "dense_cosine"


class SimpleVectorIndex:
    """Search dense vectors by scanning every record and sorting by cosine score."""

    def __init__(self, records: list[IndexRecord]) -> None:
        self.records = records

    def search(self, query_vector: list[float], top_k: int = 5) -> list[DenseSearchResult]:
        """Return the top-k records closest to the query vector."""

        if top_k <= 0:
            return []

        results: list[DenseSearchResult] = []
        for record in self.records:
            if record.dense_vector is None:
                continue
            score = cosine_similarity(query_vector, record.dense_vector)
            results.append(DenseSearchResult(record=record, score=score))

        return sorted(results, key=lambda result: result.score, reverse=True)[:top_k]
