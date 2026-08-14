"""Pluggable semantic encoders for learned memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    """Batch embedding boundary used without coupling memory to one vendor."""

    provider_id: str
    model_id: str
    learned: bool

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one finite, fixed-width vector per input text."""


@dataclass
class SentenceTransformerEmbeddingProvider:
    """Optional local learned encoder, loaded lazily outside the core package."""

    model_id: str = "sentence-transformers/all-MiniLM-L6-v2"
    provider_id: str = "sentence-transformers"
    learned: bool = True
    _model: object | None = field(default=None, init=False, repr=False)
    _cache: dict[str, list[float]] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        requested = list(texts)
        with self._lock:
            missing = list(dict.fromkeys(text for text in requested if text not in self._cache))
            if missing:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError as exc:  # pragma: no cover - optional runtime
                        raise RuntimeError(
                            "install the benchmarks extra to enable learned memory embeddings"
                        ) from exc
                    self._model = SentenceTransformer(self.model_id)
                values = self._model.encode(missing, convert_to_numpy=True)  # type: ignore[attr-defined]
                vectors = [list(map(float, row)) for row in values.tolist()]
                if len(vectors) != len(missing):
                    raise RuntimeError("embedding_provider_result_count_mismatch")
                self._cache.update(zip(missing, vectors, strict=True))
            # Copies prevent a caller from mutating the shared cache in place.
            return [list(self._cache[text]) for text in requested]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return bounded cosine similarity for validated equal-width vectors."""

    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
