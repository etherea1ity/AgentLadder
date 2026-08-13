"""Owner-scoped long-term-memory management API."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.dependencies import get_memory_scope, get_memory_service
from apps.api.schemas import (
    CreateMemoryRequest,
    DeleteMemoryResponse,
    ListMemoriesResponse,
    MemoryRecordResponse,
    SearchMemoriesResponse,
    UpdateMemoryRequest,
)
from klara.memory import (
    MemoryKind,
    MemoryNotFoundError,
    MemoryProvenance,
    MemoryScope,
    MemorySensitivity,
    MemoryService,
)


router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=ListMemoriesResponse)
def list_memories(
    service: MemoryService = Depends(get_memory_service),
    scope: MemoryScope = Depends(get_memory_scope),
) -> dict[str, object]:
    records = service.list_records(scope=scope)
    counts = Counter(record.kind.value for record in records)
    return {
        "schema_version": "klara.memory-list.v1",
        "records": [record.to_owner_dict() for record in records],
        "counts_by_kind": dict(sorted(counts.items())),
    }


@router.post("", response_model=MemoryRecordResponse)
def create_memory(
    request: CreateMemoryRequest,
    service: MemoryService = Depends(get_memory_service),
    scope: MemoryScope = Depends(get_memory_scope),
) -> dict[str, object]:
    record = service.remember(
        scope=scope,
        content=request.content,
        kind=MemoryKind(request.kind),
        sensitivity=MemorySensitivity(request.sensitivity),
        provenance=MemoryProvenance(source_type="explicit_ui", actor_id=scope.user_id),
        confidence=request.confidence,
        ttl_seconds=request.ttl_seconds,
    )
    return record.to_owner_dict()


@router.get("/search", response_model=SearchMemoriesResponse)
def search_memories(
    q: str = Query(min_length=1),
    mode: str = Query(default="hybrid"),
    at_time: str | None = None,
    service: MemoryService = Depends(get_memory_service),
    scope: MemoryScope = Depends(get_memory_scope),
) -> dict[str, object]:
    try:
        hits = service.search(scope=scope, query=q, mode=mode, at_time=at_time)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "schema_version": "klara.memory-search.v1",
        "query": q,
        "mode": mode,
        "results": [hit.to_owner_dict() for hit in hits],
    }


@router.patch("/{memory_id}", response_model=MemoryRecordResponse)
def update_memory(
    memory_id: str,
    request: UpdateMemoryRequest,
    service: MemoryService = Depends(get_memory_service),
    scope: MemoryScope = Depends(get_memory_scope),
) -> dict[str, object]:
    try:
        record = service.update(
            scope=scope,
            memory_id=memory_id,
            content=request.content,
            actor_id=scope.user_id,
            confidence=request.confidence,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="memory_not_found") from exc
    return record.to_owner_dict()


@router.post("/{memory_id}/forget", response_model=MemoryRecordResponse)
def forget_memory(
    memory_id: str,
    service: MemoryService = Depends(get_memory_service),
    scope: MemoryScope = Depends(get_memory_scope),
) -> dict[str, object]:
    try:
        record = service.forget(scope=scope, memory_id=memory_id, actor_id=scope.user_id)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="memory_not_found") from exc
    return record.to_owner_dict()


@router.delete("/{memory_id}", response_model=DeleteMemoryResponse)
def delete_memory(
    memory_id: str,
    service: MemoryService = Depends(get_memory_service),
    scope: MemoryScope = Depends(get_memory_scope),
) -> dict[str, object]:
    try:
        return service.delete(scope=scope, memory_id=memory_id, actor_id=scope.user_id)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="memory_not_found") from exc
