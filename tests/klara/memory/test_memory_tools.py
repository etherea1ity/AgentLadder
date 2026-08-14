from __future__ import annotations

import json

from klara.core.messages import ModelResponse
from klara.core.tools import ToolCall, ToolOutputTrust, ToolResult
from klara.memory import (
    MemoryKind,
    MemoryProvenance,
    MemoryScope,
    MemoryService,
    SQLiteMemoryRepository,
)
from klara.memory.controller import MemoryRuntimeController
from klara.memory.tools import MemoryRememberTool, MemorySearchTool


def test_memory_search_keeps_content_out_of_public_trace(tmp_path) -> None:
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    scope = MemoryScope("tenant-a", "user-a")
    remember = MemoryRememberTool(service, scope)
    search = MemorySearchTool(service, scope)

    assert search.metadata.output_trust is ToolOutputTrust.UNTRUSTED

    created = remember.execute(
        {"tool_call_id": "remember-1", "content": "private preference phrase", "kind": "user_preference"}
    )
    assert created.ok is True
    result = search.execute({"tool_call_id": "search-1", "query": "preference"})

    assert "private preference phrase" in result.content
    model_payload = json.loads(result.content)
    assert set(model_payload["results"][0]) == {
        "memory_id",
        "content",
        "kind",
        "confidence",
        "occurred_at",
        "score",
        "source_type",
        "retrieval_rank",
    }
    assert model_payload["selection_order"] == "top_k_by_retrieval_score"
    assert model_payload["presentation_order"] == "chronological_after_selection"
    public = result.to_public_dict()
    assert public["content_redacted"] is True
    assert "private preference phrase" not in json.dumps(public)
    assert json.loads(public["content"])["content_exposed"] is False


def test_memory_controller_stops_successful_search_loops() -> None:
    controller = MemoryRuntimeController()
    controller.on_run_start(user_input="What did I prefer?", run_id="run-1")
    assert "already" not in controller.system_prompt_suffix()

    controller.on_tool_results(
        results=(
            ToolResult(
                tool_call_id="search-1",
                name="memory_search",
                content='{"result_count": 1}',
            ),
        )
    )

    suffix = controller.system_prompt_suffix()
    assert "Do not call memory_search again" in suffix
    assert "shortest answer span" in suffix
    assert "alternate candidates" in suffix


def test_memory_search_selects_by_relevance_then_presents_chronologically(tmp_path) -> None:
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    scope = MemoryScope("tenant-a", "user-a")
    provenance = MemoryProvenance(source_type="test", actor_id="user-a")
    service.remember(
        scope=scope,
        content="Alpha project used the red design first.",
        kind=MemoryKind.EPISODIC,
        provenance=provenance,
        valid_from="2026-01-01T00:00:00+00:00",
    )
    service.remember(
        scope=scope,
        content="Alpha project later changed to the blue design.",
        kind=MemoryKind.EPISODIC,
        provenance=provenance,
        valid_from="2026-02-01T00:00:00+00:00",
    )

    result = MemorySearchTool(service, scope).execute(
        {"tool_call_id": "search-timeline", "query": "Alpha project design", "limit": 2}
    )
    payload = json.loads(result.content)

    assert [item["occurred_at"] for item in payload["results"]] == sorted(
        item["occurred_at"] for item in payload["results"]
    )
    assert {item["retrieval_rank"] for item in payload["results"]} == {1, 2}
