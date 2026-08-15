"""Thin HTTP boundary around the provenance-pinned official Mem0 v3 SDK."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from threading import Lock, local
from time import sleep
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


MEM0_PR_HEAD = "5e941e24c2cb260f73cc6d31113a92bb1ce62d46"
EMBEDDING_DIMS = 384
_METRICS_LOCK = Lock()
_EXTRACTION_JSON_RETRIES = 0
_EXTRACTION_JSON_REQUEST_FAILURES = 0
_EXTRACTION_STATE = local()


def _parse_json_object(value: Any) -> dict[str, Any]:
    """Apply the pinned SDK's tolerant JSON cleanup, then require its schema."""

    from mem0.memory.utils import extract_json, remove_code_blocks

    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty_json_content")
    cleaned = remove_code_blocks(value)
    try:
        parsed = json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        parsed = json.loads(extract_json(cleaned), strict=False)
    if not isinstance(parsed, dict):
        raise ValueError("json_content_not_object")
    memories = parsed.get("memory")
    if not isinstance(memories, list):
        raise ValueError("json_content_missing_memory_list")
    return parsed


def _install_strict_extraction_retry(memory: Any) -> None:
    """Retry only malformed JSON that the PR otherwise hides as zero memories."""

    original = memory.llm.generate_response

    def strict_generate_response(*args: Any, **kwargs: Any) -> Any:
        global _EXTRACTION_JSON_REQUEST_FAILURES, _EXTRACTION_JSON_RETRIES

        response_format = kwargs.get("response_format")
        requires_json = (
            isinstance(response_format, dict)
            and response_format.get("type") == "json_object"
        )
        for attempt in range(3):
            value = original(*args, **kwargs)
            if not requires_json:
                return value
            try:
                _parse_json_object(value)
                return value
            except (TypeError, ValueError, json.JSONDecodeError):
                if attempt < 2:
                    with _METRICS_LOCK:
                        _EXTRACTION_JSON_RETRIES += 1
                    sleep(2**attempt)
                    continue
                with _METRICS_LOCK:
                    _EXTRACTION_JSON_REQUEST_FAILURES += 1
                _EXTRACTION_STATE.failed = True
                raise RuntimeError("mem0_extraction_json_invalid_after_retries")
        raise AssertionError("unreachable_extraction_retry_state")

    memory.llm.generate_response = strict_generate_response


class AddRequest(BaseModel):
    """One official LoCoMo turn plus observational source metadata."""

    messages: list[dict[str, str]]
    user_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    """A user-scoped Mem0 v3 search request."""

    query: str
    user_id: str
    limit: int = Field(default=20, ge=1, le=200)


def _run_add_with_strict_boundary(memory: Any, request: AddRequest) -> dict[str, Any]:
    """Surface a malformed-JSON signal even when the pinned SDK catches it."""

    _EXTRACTION_STATE.failed = False
    result = memory.add(
        request.messages,
        user_id=request.user_id,
        metadata=request.metadata,
    )
    if bool(getattr(_EXTRACTION_STATE, "failed", False)):
        raise RuntimeError("mem0_extraction_json_invalid_after_retries")
    return result


def _config() -> dict[str, Any]:
    """Build the fixed same-control Mem0 configuration without logging secrets."""

    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    qdrant_host = os.getenv("MEM0_QDRANT_HOST", "").strip()
    qdrant_config: dict[str, Any] = {
        "collection_name": os.getenv(
            "MEM0_COLLECTION", "agentladder_mem0_v3_pr4805"
        ),
        "embedding_model_dims": EMBEDDING_DIMS,
    }
    if qdrant_host:
        qdrant_config.update(
            {
                "host": qdrant_host,
                "port": int(os.getenv("MEM0_QDRANT_PORT", "6333")),
                "path": None,
            }
        )
    else:
        qdrant_config["path"] = os.getenv("QDRANT_PATH", "/app/qdrant")
    return {
        "version": "v1.1",
        "llm": {
            "provider": "deepseek",
            "config": {
                "model": os.getenv("MEM0_LLM_MODEL", "deepseek-v4-flash"),
                "deepseek_base_url": os.getenv(
                    "MEM0_LLM_BASE_URL", "https://api.deepseek.com/v1"
                ),
                "temperature": 0.1,
                # 512 tokens produced an empty content field and 1400 still
                # truncated some complex LoCoMo turns. The bounded preflight
                # froze 2400 before the formal checkpoint was accepted.
                "max_tokens": 2400,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": os.getenv(
                    "MEM0_EMBEDDING_MODEL",
                    "sentence-transformers/all-MiniLM-L6-v2",
                ),
                "embedding_dims": EMBEDDING_DIMS,
                "api_key": "agentladder-local-embedding",
                "openai_base_url": os.getenv(
                    "MEM0_EMBEDDING_BASE_URL",
                    "http://host.docker.internal:18989/v1",
                ),
            },
        },
        "vector_store": {"provider": "qdrant", "config": qdrant_config},
        "history_db_path": os.getenv(
            "MEM0_HISTORY_DB", "/app/history/history.db"
        ),
    }


@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Initialize the exact official SDK once for the single-worker container."""

    from mem0 import Memory
    import spacy

    app.state.memory = await asyncio.to_thread(Memory.from_config, _config())
    _install_strict_extraction_retry(app.state.memory)
    encoder = await asyncio.to_thread(
        app.state.memory.vector_store._get_bm25_encoder
    )
    if encoder is None:
        raise RuntimeError("official_mem0_bm25_encoder_unavailable")
    await asyncio.to_thread(spacy.load, "en_core_web_sm")
    app.state.bm25_enabled = True
    app.state.entity_runtime_available = True
    yield


app = FastAPI(title="AgentLadder Mem0 Comparable Adapter", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Expose only provenance and non-secret control facts."""

    return {
        "status": "ok",
        "mem0_pr_head": MEM0_PR_HEAD,
        "llm_model": os.getenv("MEM0_LLM_MODEL", "deepseek-v4-flash"),
        "embedding_model": os.getenv(
            "MEM0_EMBEDDING_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        ),
        "embedding_dims": EMBEDDING_DIMS,
        "embedding_provider": "official-openai-compatible",
        "qdrant_mode": (
            "service" if os.getenv("MEM0_QDRANT_HOST", "").strip() else "embedded"
        ),
        "bm25_enabled": bool(app.state.bm25_enabled),
        "entity_runtime_available": bool(app.state.entity_runtime_available),
        "strict_extraction_json_boundary": True,
        "extraction_json_retries": _EXTRACTION_JSON_RETRIES,
        "extraction_json_request_failures": _EXTRACTION_JSON_REQUEST_FAILURES,
    }


@app.post("/memories")
async def add_memories(request: AddRequest) -> dict[str, Any]:
    """Run official v3 formation while retaining source IDs as metadata."""

    try:
        return await asyncio.to_thread(
            _run_add_with_strict_boundary, app.state.memory, request
        )
    except Exception as exc:  # pragma: no cover - live container boundary
        raise HTTPException(status_code=500, detail=type(exc).__name__) from exc


@app.post("/search")
async def search_memories(request: SearchRequest) -> dict[str, Any]:
    """Map the benchmark user scope to the v3 ``filters`` search contract."""

    try:
        result = await asyncio.to_thread(
            app.state.memory.search,
            request.query,
            top_k=request.limit,
            filters={"user_id": request.user_id},
        )
        if isinstance(result, dict):
            return result
        return {"results": result if isinstance(result, list) else []}
    except Exception as exc:  # pragma: no cover - live container boundary
        raise HTTPException(status_code=500, detail=type(exc).__name__) from exc
