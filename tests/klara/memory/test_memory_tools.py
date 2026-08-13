from __future__ import annotations

import json

from klara.core.messages import ModelResponse
from klara.core.tools import ToolCall
from klara.memory import MemoryScope, MemoryService, SQLiteMemoryRepository
from klara.memory.tools import MemoryRememberTool, MemorySearchTool


def test_memory_search_keeps_content_out_of_public_trace(tmp_path) -> None:
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    scope = MemoryScope("tenant-a", "user-a")
    remember = MemoryRememberTool(service, scope)
    search = MemorySearchTool(service, scope)

    created = remember.execute(
        {"tool_call_id": "remember-1", "content": "private preference phrase", "kind": "user_preference"}
    )
    assert created.ok is True
    result = search.execute({"tool_call_id": "search-1", "query": "preference"})

    assert "private preference phrase" in result.content
    public = result.to_public_dict()
    assert public["content_redacted"] is True
    assert "private preference phrase" not in json.dumps(public)
    assert json.loads(public["content"])["content_exposed"] is False
