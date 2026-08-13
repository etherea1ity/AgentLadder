from __future__ import annotations

from apps.api.dependencies import get_memory_scope, get_memory_service
from apps.api.main import app
from apps.api.routes.memory import (
    create_memory,
    delete_memory,
    list_memories,
    search_memories,
    update_memory,
)
from apps.api.schemas import CreateMemoryRequest, UpdateMemoryRequest
from klara.memory import MemoryScope, MemoryService, SQLiteMemoryRepository


def test_memory_api_remember_search_update_and_delete(tmp_path) -> None:
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    scope = MemoryScope("tenant-test", "user-test", agent_id="klara")
    assert "/api/memory" in {route.path for route in app.routes}
    created = create_memory(
        CreateMemoryRequest(content="Prefer concise answers", kind="user_preference"),
        service,
        scope,
    )
    memory_id = created["memory_id"]
    assert list_memories(service, scope)["counts_by_kind"] == {"user_preference": 1}
    search = search_memories("concise answer", "hybrid", None, service, scope)
    assert search["results"][0]["memory_id"] == memory_id

    updated = update_memory(
        memory_id,
        UpdateMemoryRequest(content="Prefer detailed answers"),
        service,
        scope,
    )
    current_id = updated["memory_id"]
    deleted = delete_memory(current_id, service, scope)
    assert deleted["deletion_verified"] is True
    assert search_memories("detailed", "hybrid", None, service, scope)["results"] == []
