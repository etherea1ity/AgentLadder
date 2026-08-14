"""Dependency-free hybrid retrieval for scoped Klara memories."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
import hashlib
import math
import re

from klara.memory.models import MemoryRecord, MemorySearchHit
from klara.memory.semantic import EmbeddingProvider, cosine_similarity


_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_ENTITY_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9_-]+|[A-Za-z]+\d+[A-Za-z0-9_-]*)\b")


@dataclass(frozen=True)
class RetrievalWeights:
    """Transparent score weights for the hybrid ranker."""

    lexical: float = 0.24
    semantic: float = 0.36
    entity: float = 0.18
    recency: float = 0.04
    temporal: float = 0.08
    bm25: float = 0.10


def rank_memories(
    records: list[MemoryRecord],
    *,
    query: str,
    mode: str = "hybrid",
    at_time: str | None = None,
    limit: int = 8,
    now: str | None = None,
    weights: RetrievalWeights = RetrievalWeights(),
    embedding_provider: EmbeddingProvider | None = None,
) -> list[MemorySearchHit]:
    """Rank records with one named ablation strategy."""

    if limit < 1:
        return []
    evaluated_now = _parse_time(now) if now else datetime.now(UTC)
    query_terms = _terms(query)
    query_vector = _char_ngrams(query)
    query_entities = _entities(query)
    (
        corpus_terms,
        document_frequency,
        average_document_length,
        vector_document_frequency,
        weighted_document_vectors,
    ) = _corpus_features(tuple(record.content for record in records))
    weighted_query_vector = _weighted_ngrams(
        query_vector,
        vector_document_frequency,
        len(records),
    )
    hits: list[MemorySearchHit] = []
    # Score each already-authorized candidate; this function never widens scope.
    learned_semantic: list[float] | None = None
    if embedding_provider is not None and records:
        vectors = embedding_provider.embed_batch(
            [query, *(record.content for record in records)]
        )
        if len(vectors) != len(records) + 1:
            raise ValueError("memory_embedding_batch_size_mismatch")
        learned_semantic = [
            cosine_similarity(vectors[0], vector) for vector in vectors[1:]
        ]
    components: list[
        tuple[MemoryRecord, float, float, float | None, float, float, float, float]
    ] = []
    for index, (record, term_counts, weighted_document_vector) in enumerate(zip(
        records, corpus_terms, weighted_document_vectors, strict=True
    )):
        lexical = _jaccard(query_terms, _terms(record.content))
        sparse_semantic = _weighted_cosine(
            weighted_query_vector, weighted_document_vector
        )
        dense_semantic = (
            learned_semantic[index] if learned_semantic is not None else None
        )
        entity = _jaccard(query_entities, _entities(record.content))
        recency = _recency(record.updated_at, evaluated_now)
        temporal = _temporal_fit(record, at_time)
        bm25 = _bm25(
            query_terms,
            term_counts,
            document_frequency,
            document_count=len(records),
            average_document_length=average_document_length,
        )
        components.append(
            (
                record,
                lexical,
                sparse_semantic,
                dense_semantic,
                entity,
                recency,
                temporal,
                bm25,
            )
        )
    fused_semantic = _dense_sparse_rank_fusion(components)
    turn_scores = {
        _turn_index(record): fused_semantic[record.memory_id]
        for record, *_ in components
        if _turn_index(record) is not None
    }
    for record, lexical, sparse, dense, entity, recency, temporal, bm25 in components:
        semantic = dense if mode == "vector" and dense is not None else fused_semantic[record.memory_id]
        previous_turn_similarity = max(
            (
                turn_scores.get((_turn_index(record) or 0) - offset, 0.0)
                for offset in (1, 2)
            ),
            default=0.0,
        ) if _turn_index(record) is not None else 0.0
        score = _mode_score(
            mode,
            lexical=lexical,
            semantic=semantic,
            entity=entity,
            recency=recency,
            temporal=temporal,
            bm25=bm25,
            previous_turn_similarity=previous_turn_similarity,
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


def _dense_sparse_rank_fusion(
    components: list[
        tuple[MemoryRecord, float, float, float | None, float, float, float, float]
    ],
    *,
    rrf_k: int = 60,
) -> dict[str, float]:
    """Fuse incomparable dense and sparse scores by reciprocal rank."""

    if not components:
        return {}
    if all(item[3] is None for item in components):
        return {item[0].memory_id: item[2] for item in components}
    sparse_order = sorted(components, key=lambda item: (-item[2], item[0].memory_id))
    dense_order = sorted(
        components,
        key=lambda item: (-(item[3] if item[3] is not None else -1.0), item[0].memory_id),
    )
    sparse_rank = {item[0].memory_id: rank for rank, item in enumerate(sparse_order, 1)}
    dense_rank = {item[0].memory_id: rank for rank, item in enumerate(dense_order, 1)}
    maximum = 2.0 / (rrf_k + 1)
    return {
        item[0].memory_id: (
            1.0 / (rrf_k + sparse_rank[item[0].memory_id])
            + 1.0 / (rrf_k + dense_rank[item[0].memory_id])
        )
        / maximum
        for item in components
    }


def _mode_score(
    mode: str,
    *,
    lexical: float,
    semantic: float,
    entity: float,
    recency: float,
    temporal: float,
    bm25: float,
    previous_turn_similarity: float,
    weights: RetrievalWeights,
) -> float:
    if mode == "full_context":
        return 1.0
    if mode == "recent":
        return recency
    if mode == "lexical":
        return bm25
    if mode == "vector":
        return semantic
    if mode in {"semantic_recency", "mem0_compatible"}:
        return semantic * 0.7 + recency * 0.3
    if mode != "hybrid":
        raise ValueError(f"unknown_memory_retrieval_mode:{mode}")
    # Conversational memories often store a user's question immediately before
    # the answering turn. Propagate only that local structural signal; no labels
    # or answer text participate in ranking. BM25 and the other signals break
    # near-ties without drowning the structural semantic score.
    return (
        semantic
        + previous_turn_similarity * 0.5
        + bm25 * 0.10
        + lexical * 0.04
        + entity * 0.03
        + temporal * 0.02
        + recency * 0.01
    )


@lru_cache(maxsize=32_768)
def _terms(text: str) -> frozenset[str]:
    return frozenset(item.lower() for item in _WORD_RE.findall(text))


@lru_cache(maxsize=32_768)
def _term_counts(text: str) -> Counter[str]:
    return Counter(item.lower() for item in _WORD_RE.findall(text))


@lru_cache(maxsize=32_768)
def _entities(text: str) -> frozenset[str]:
    return frozenset(item.lower() for item in _ENTITY_RE.findall(text))


@lru_cache(maxsize=32_768)
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


@lru_cache(maxsize=32_768)
def _char_ngrams(text: str) -> Counter[str]:
    normalized = " ".join(text.casefold().split())
    padded_words = [f" {word} " for word in normalized.split()]
    grams: Counter[str] = Counter()
    for word in padded_words:
        for size in (3, 4, 5):
            for index in range(max(0, len(word) - size + 1)):
                grams[word[index : index + size]] += 1
    if not grams and normalized:
        grams[normalized] = 1
    return grams


def _weighted_ngrams(
    vector: Counter[str],
    document_frequency: Counter[str],
    document_count: int,
) -> dict[str, float]:
    if not vector or document_count < 1:
        return {}
    return {
        gram: (1.0 + math.log(frequency))
        * (math.log((1.0 + document_count) / (1.0 + document_frequency.get(gram, 0))) + 1.0)
        for gram, frequency in vector.items()
    }


def _weighted_cosine(query_weights: dict[str, float], document_weights: dict[str, float]) -> float:
    if not query_weights or not document_weights:
        return 0.0
    shared = sum(value * document_weights.get(gram, 0.0) for gram, value in query_weights.items())
    query_norm = math.sqrt(sum(value * value for value in query_weights.values()))
    document_norm = math.sqrt(sum(value * value for value in document_weights.values()))
    return shared / (query_norm * document_norm) if query_norm and document_norm else 0.0


@lru_cache(maxsize=128)
def _corpus_features(
    contents: tuple[str, ...],
) -> tuple[
    tuple[Counter[str], ...],
    Counter[str],
    float,
    Counter[str],
    tuple[dict[str, float], ...],
]:
    term_counts = tuple(_term_counts(content) for content in contents)
    document_frequency = Counter(term for counts in term_counts for term in counts)
    average_document_length = (
        sum(sum(counts.values()) for counts in term_counts) / len(term_counts)
        if term_counts
        else 0.0
    )
    vectors = tuple(_char_ngrams(content) for content in contents)
    vector_document_frequency = Counter(gram for vector in vectors for gram in vector)
    weighted_vectors = tuple(
        _weighted_ngrams(vector, vector_document_frequency, len(contents))
        for vector in vectors
    )
    return (
        term_counts,
        document_frequency,
        average_document_length,
        vector_document_frequency,
        weighted_vectors,
    )


def _turn_index(record: MemoryRecord) -> int | None:
    value = record.metadata.get("conversation_turn_index")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _cosine(left: Counter[int], right: Counter[int]) -> float:
    if not left or not right:
        return 0.0
    shared = sum(value * right.get(key, 0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return shared / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _jaccard(left: set[str] | frozenset[str], right: set[str] | frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _bm25(
    query_terms: frozenset[str],
    document_terms: Counter[str],
    document_frequency: Counter[str],
    *,
    document_count: int,
    average_document_length: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_terms or not document_terms or document_count < 1:
        return 0.0
    length = sum(document_terms.values())
    score = 0.0
    for term in query_terms:
        frequency = document_terms.get(term, 0)
        if not frequency:
            continue
        frequency_in_corpus = document_frequency.get(term, 0)
        inverse_document_frequency = math.log(
            1.0 + (document_count - frequency_in_corpus + 0.5) / (frequency_in_corpus + 0.5)
        )
        denominator = frequency + k1 * (
            1.0 - b + b * length / max(1.0, average_document_length)
        )
        score += inverse_document_frequency * frequency * (k1 + 1.0) / denominator
    return score / (1.0 + score)


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
