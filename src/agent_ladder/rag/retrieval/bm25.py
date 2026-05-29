"""Transparent BM25 retriever for Klara's small local knowledge library."""

from __future__ import annotations

import math
from collections import Counter

from pydantic import BaseModel

from agent_ladder.rag.indexing.index_record import IndexRecord
from agent_ladder.rag.retrieval.tokenizer import tokenize


class BM25SearchResult(BaseModel):
    record: IndexRecord
    score: float
    rank: int
    matched_tokens: list[str]
    score_type: str = "bm25"


class BM25Retriever:
    def __init__(self, records: list[IndexRecord], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.records = records
        self.k1 = k1
        self.b = b
        self._tokens_by_record: dict[str, list[str]] = {}
        self._tf_by_record: dict[str, Counter[str]] = {}
        self._df: Counter[str] = Counter()
        self._avgdl = 0.0
        self._build()

    def search(self, query: str, top_k: int = 5) -> list[BM25SearchResult]:
        if top_k <= 0 or not self.records:
            return []
        query_tokens = list(dict.fromkeys(tokenize(query)))
        if not query_tokens:
            return []
        scored: list[BM25SearchResult] = []
        for record in self.records:
            tokens = self._tokens_by_record.get(record.record_id, [])
            tf = self._tf_by_record.get(record.record_id, Counter())
            if not tokens:
                continue
            score = 0.0
            matched: list[str] = []
            for token in query_tokens:
                freq = tf[token]
                if freq <= 0:
                    continue
                matched.append(token)
                score += self._idf(token) * self._term_score(freq, len(tokens))
            if score > 0:
                scored.append(BM25SearchResult(record=record, score=score, rank=0, matched_tokens=matched))
        scored.sort(key=lambda item: item.score, reverse=True)
        return [item.model_copy(update={"rank": index + 1}) for index, item in enumerate(scored[:top_k])]

    def _build(self) -> None:
        lengths: list[int] = []
        for record in self.records:
            tokens = record.sparse_tokens or tokenize(_record_search_text(record))
            self._tokens_by_record[record.record_id] = tokens
            counter = Counter(tokens)
            self._tf_by_record[record.record_id] = counter
            self._df.update(counter.keys())
            lengths.append(len(tokens))
        self._avgdl = sum(lengths) / len(lengths) if lengths else 0.0

    def _idf(self, token: str) -> float:
        n = len(self.records)
        df = self._df[token]
        return math.log(1 + (n - df + 0.5) / (df + 0.5)) if n and df else 0.0

    def _term_score(self, frequency: int, doc_length: int) -> float:
        if frequency <= 0:
            return 0.0
        avgdl = self._avgdl or 1.0
        denominator = frequency + self.k1 * (1 - self.b + self.b * doc_length / avgdl)
        return frequency * (self.k1 + 1) / denominator


def _record_search_text(record: IndexRecord) -> str:
    metadata = record.metadata
    return "\n".join(
        part
        for part in [
            metadata.title,
            metadata.summary,
            metadata.chapter,
            metadata.version,
            " ".join(metadata.tags),
            record.text,
        ]
        if part
    )
