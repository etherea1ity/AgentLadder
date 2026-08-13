from __future__ import annotations

import json
import threading

import pytest

from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.core.messages import ModelResponse
from klara.core.tools import ToolCall
from klara.planning.todo import TodoItem, TodoPlan


class PlanningLlm:
    def __init__(self) -> None:
        self.calls = 0
        self.visible_tools: tuple[str, ...] = ()

    def complete(self, **kwargs: object) -> ModelResponse:
        self.calls += 1
        self.visible_tools = tuple(tool.name for tool in kwargs["tools"])
        if self.calls == 1:
            return ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        id="activity-1",
                        name="update_activity",
                        arguments={"text": "I will make the steps visible first."},
                    ),
                    ToolCall(
                        id="todo-1",
                        name="todo_write",
                        arguments={
                            "operation": "replace",
                            "items": [
                                {"id": "plan", "title": "Create the plan", "status": "completed"},
                                {"id": "build", "title": "Build the feature", "status": "in_progress"},
                                {"id": "verify", "title": "Verify the feature", "status": "pending"},
                            ],
                        },
                    ),
                ),
            )
        return ModelResponse(content="The plan is visible and work has started.")


def test_todo_plan_is_versioned_persistent_and_rejects_stale_writes(tmp_path) -> None:
    root = tmp_path / "app"
    store = JsonlAppStore(root)
    session = store.create_session()
    first = store.update_todo_plan(
        session.session_id,
        "replace",
        [TodoItem(id="one", title="One", status="in_progress")],
    )
    second = store.update_todo_plan(
        session.session_id,
        "merge",
        [TodoItem(id="one", title="One", status="completed")],
    )

    restored = JsonlAppStore(root).get_todo_plan(session.session_id)
    assert first.version == 1
    assert second.version == 2
    assert restored == second

    with pytest.raises(ValueError, match="version must increase"):
        store.save_todo_plan(
            TodoPlan(session_id=session.session_id, version=2, items=[])
        )


def test_concurrent_merges_receive_distinct_monotonic_versions(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    failures: list[Exception] = []

    def update(index: int) -> None:
        try:
            store.update_todo_plan(
                session.session_id,
                "merge",
                [TodoItem(id=f"item-{index}", title=f"Item {index}")],
            )
        except Exception as exc:  # pragma: no cover - captured for assertion
            failures.append(exc)

    threads = [threading.Thread(target=update, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    latest = store.get_todo_plan(session.session_id)
    versions = [
        json.loads(line)["version"]
        for line in store.todo_plans_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert failures == []
    assert latest is not None
    assert latest.version == 8
    assert len(latest.items) == 8
    assert versions == list(range(1, 9))


def test_model_plan_update_reaches_store_sse_and_jsonl_trace(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    trace_path = tmp_path / "traces" / "runs.jsonl"
    llm = PlanningLlm()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=llm,
        trace_path=str(trace_path),
        default_model="test-model",
        answer_chunk_delay_ms=0,
    )

    created = service.create_run(session.session_id, "Make and follow a short plan")
    service._threads[created.run_id].join(timeout=5)

    plan = store.get_todo_plan(session.session_id)
    plan_event = next(
        event
        for event in store.list_events(created.run_id)
        if event.event_type == "todo_plan_updated"
    )
    trace_events = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tool_trace = next(
        event
        for event in trace_events
        if event["type"] == "tool.completed"
        and event["payload"]["tool_result"]["name"] == "todo_write"
    )

    assert "todo_write" in llm.visible_tools
    assert plan is not None
    assert plan.version == 1
    assert [item.status for item in plan.items] == ["completed", "in_progress", "pending"]
    assert plan_event.payload == plan.model_dump(mode="json")
    assert json.loads(tool_trace["payload"]["tool_result"]["content"])["version"] == 1


def test_session_delete_purges_the_current_plan(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    store.update_todo_plan(
        session.session_id,
        "replace",
        [TodoItem(id="one", title="One", status="pending")],
    )

    store.delete_session(session.session_id, tmp_path / "traces.jsonl")

    assert store.get_todo_plan(session.session_id) is None
    assert not store.todo_plans_path.read_text(encoding="utf-8").strip()
