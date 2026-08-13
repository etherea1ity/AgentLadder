"""Dependency-free hybrid retrieval for scoped Klara memories."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import math
import re

from klara.memory.models import MemoryRecord, MemorySearchHit


_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_ENTITY_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9_-]+|[A-Za-z]+\d+[A-Za-z0-9_-]*)\b")


@dataclass(frozen=True)
class RetrievalWeights:
    """Transparent score weights for the hybrid ranker."""

    lexical: float = 0.30
    semantic: float = 0.34
    entity: float = 0.14
    recency: float = 0.10
    temporal: float = 0.12


def rank_memories(
    records: list[MemoryRecord],
    *,
    query: str,
    mode: str = "hybrid",
    at_time: str | None = None,
    limit: int = 8,
    now: str | None = None,
    weights: RetrievalWeights = RetrievalWeights(),
) -> list[MemorySearchHit]:
    """Rank records with one named ablation strategy."""

    if limit < 1:
        return []
    evaluated_now = _parse_time(now) if now else datetime.now(UTC)
    query_terms = _terms(query)
    query_vector = _hash_vector(query)
    query_entities = _entities(query)
    hits: list[MemorySearchHit] = []
    # Score each already-authorized candidate; this function never widens scope.
    for record in records:
        lexical = _jaccard(query_terms, _terms(record.content))
        semantic = _cosine(query_vector, _hash_vector(record.content))
        entity = _jaccard(query_entities, _entities(record.content))
        recency = _recency(record.updated_at, evaluated_now)
        temporal = _temporal_fit(record, at_time)
        score = _mode_score(
            mode,
            lexical=lexical,
            semantic=semantic,
            entity=entity,
            recency=recency,
            temporal=temporal,
            weights=weights,
        )
        hits.append(
            MemorySearchHit(
                record=record,
                score=score,
                lexical_score=lexical,
                semantic_score=semantic,
                entity_score=entity,
                recency_score=recency,
                temporal_score=temporal,
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.record.memory_id))
    return hits[:limit]


def _mode_score(
    mode: str,
    *,
    lexical: float,
    semantic: float,
    entity: float,
    recency: float,
    temporal: float,
    weights: RetrievalWeights,
) -> float:
    if mode == "full_context":
        return 1.0
    if mode == "recent":
        return recency
    if mode == "lexical":
        return lexical
    if mode == "vector":
        return semantic
    if mode == "mem0_compatible":
        return semantic * 0.7 + recency * 0.3
    if mode != "hybrid":
        raise ValueError(f"unknown_memory_retrieval_mode:{mode}")
    return (
        lexical * weights.lexical
        + semantic * weights.semantic
        + entity * weights.entity
        + recency * weights.recency
        + temporal * weights.temporal
    )


def _terms(text: str) -> set[str]:
    return {item.lower() for item in _WORD_RE.findall(text)}


def _entities(text: str) -> set[str]:
    return {item.lower() for item in _ENTITY_RE.findall(text)}


def _hash_vector(text: str, dimensions: int = 128) -> Counter[int]:
    normalized = " ".join(text.lower().split())
    grams = [normalized[index : index + 3] for index in range(max(0, len(normalized) - 2))]
    if not grams and normalized:
        grams = [normalized]
    return Counter(
        int.from_bytes(hashlib.sha256(gram.encode("utf-8")).digest()[:4], "big")
        % dimensions
        for gram in grams
    )


def _cosine(left: Counter[int], right: Counter[int]) -> float:
    if not left or not right:
        return 0.0
    shared = sum(value * right.get(key, 0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return shared / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _recency(timestamp: str, now: datetime) -> float:
    age_days = max(0.0, (now - _parse_time(timestamp)).total_seconds() / 86_400)
    return math.exp(-age_days / 180.0)


def _temporal_fit(record: MemoryRecord, at_time: str | None) -> float:
    if at_time is None:
        return 1.0 if record.valid_to is None else 0.2
    target = _parse_time(at_time)
    if record.valid_from and target < _parse_time(record.valid_from):
        return 0.0
    if record.valid_to and target >= _parse_time(record.valid_to):
        return 0.0
    return 1.0


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
