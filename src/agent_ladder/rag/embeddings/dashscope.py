"""DashScope OpenAI-compatible dense embedding client."""

import os

from openai import OpenAI

from agent_ladder.rag.embeddings.base import BaseEmbedder


class DashScopeEmbedder(BaseEmbedder):
    """Create dense embeddings with DashScope's OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY is required for DashScope embeddings")

        self.model = model or os.getenv("AGENT_LADDER_EMBEDDING_MODEL", "text-embedding-v4")
        self.base_url = base_url or os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.dimensions = dimensions or int(os.getenv("AGENT_LADDER_EMBEDDING_DIMENSIONS", "1024"))
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string as a dense float vector."""

        vectors = self.embed_texts([text])
        return vectors[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in one request when the provider supports it."""

        if not texts:
            return []

        vectors: list[list[float]] = []
        batch_size = 10
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self.dimensions,
                encoding_format="float",
            )
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
        return vectors
