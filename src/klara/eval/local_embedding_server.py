"""OpenAI-compatible local endpoint for the frozen LoCoMo embedding model."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSIONS = 384


class EmbeddingRequest(BaseModel):
    """Subset of the OpenAI embedding request used by the official Mem0 SDK."""

    input: str | list[str]
    model: str
    encoding_format: str | None = None
    dimensions: int | None = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from sentence_transformers import SentenceTransformer

    app.state.model = SentenceTransformer(MODEL)
    yield


app = FastAPI(title="AgentLadder Frozen Local Embedding", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Return non-secret model identity and vector dimensions."""

    return {"status": "ok", "model": MODEL, "dimensions": DIMENSIONS}


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest) -> dict[str, Any]:
    """Encode one or more strings in the OpenAI response shape."""

    texts = [request.input] if isinstance(request.input, str) else request.input
    vectors = app.state.model.encode(texts, convert_to_numpy=True)
    return {
        "object": "list",
        "model": MODEL,
        "data": [
            {
                "object": "embedding",
                "index": index,
                "embedding": vector.tolist(),
            }
            for index, vector in enumerate(vectors)
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }
