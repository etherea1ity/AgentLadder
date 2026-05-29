"""Embedding interfaces for Klara's RAG pipeline."""

from abc import ABC, abstractmethod


class BaseEmbedder(ABC):
    """Convert text into dense vectors."""

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple text strings while preserving order."""

        return [self.embed_text(text) for text in texts]
