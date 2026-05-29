"""Vector similarity helpers for the minimal dense index."""

from math import sqrt


def dot_product(a: list[float], b: list[float]) -> float:
    """Return the dot product of two equal-length vectors."""

    _ensure_same_dimension(a, b)
    return sum(left * right for left, right in zip(a, b, strict=True))


def vector_norm(vector: list[float]) -> float:
    """Return the Euclidean norm of a vector."""

    return sqrt(sum(value * value for value in vector))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity for two vectors."""

    _ensure_same_dimension(a, b)
    norm_a = vector_norm(a)
    norm_b = vector_norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product(a, b) / (norm_a * norm_b)


def _ensure_same_dimension(a: list[float], b: list[float]) -> None:
    if len(a) != len(b):
        raise ValueError(f"Vector dimensions must match: {len(a)} != {len(b)}")
