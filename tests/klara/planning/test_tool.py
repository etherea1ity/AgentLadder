from __future__ import annotations

import json

from klara.planning.todo import TodoItem, TodoOperation, TodoPlan, apply_todo_update
from klara.planning.tool import TodoWriteTool
from klara.core.tools import ToolSideEffect


class MemoryTodoStore:
    def __init__(self) -> None:
        self.plan: TodoPlan | None = None

    def update_todo_plan(
        self,
        session_id: str,
        operation: TodoOperation,
        items: list[TodoItem],
    ) -> TodoPlan:
        next_plan = apply_todo_update(
            session_id=session_id,
            existing=self.plan,
            operation=operation,
            items=items,
        )
        self.plan = next_plan
        return next_plan


def test_todo_write_returns_the_persisted_public_plan() -> None:
    store = MemoryTodoStore()
    tool = TodoWriteTool(session_id="sess-1", store=store)

    result = tool.run(
        {
            "tool_call_id": "call-1",
            "operation": "replace",
            "items": [
                {"id": "inspect", "title": "Inspect repository", "status": "completed"},
                {"id": "build", "title": "Build planning", "status": "in_progress"},
            ],
        }
    )

    assert result.ok is True
    assert result.tool_call_id == "call-1"
    assert json.loads(result.content) == store.plan.model_dump(mode="json")
    assert tool.metadata.side_effect is ToolSideEffect.WRITE
    assert tool.metadata.parallel_safe is False
    assert tool.metadata.max_output_chars >= 12000


def test_invalid_update_is_an_observation_and_keeps_previous_plan() -> None:
    store = MemoryTodoStore()
    tool = TodoWriteTool(session_id="sess-1", store=store)
    first = tool.run(
        {
            "operation": "replace",
            "items": [{"id": "build", "title": "Build", "status": "in_progress"}],
        }
    )
    previous = store.plan

    failed = tool.run(
        {
            "operation": "merge",
            "items": [{"id": "verify", "title": "Verify", "status": "in_progress"}],
        }
    )

    assert first.ok is True
    assert failed.ok is False
    assert "at most one" in (failed.error or "")
    assert store.plan == previous


def test_todo_write_rejects_unknown_fields_and_invalid_ids() -> None:
    tool = TodoWriteTool(session_id="sess-1", store=MemoryTodoStore())

    result = tool.run(
        {
            "operation": "replace",
            "items": [{"id": "Not valid", "title": "No", "status": "pending", "extra": True}],
        }
    )

    assert result.ok is False
    assert result.content == ""


def test_todo_write_rejects_unstarted_replacement_plan() -> None:
    tool = TodoWriteTool(session_id="sess-1", store=MemoryTodoStore())

    result = tool.run(
        {
            "operation": "replace",
            "items": [
                {"id": "inspect", "title": "Inspect", "status": "pending"},
                {"id": "verify", "title": "Verify", "status": "pending"},
            ],
        }
    )

    assert result.ok is False
    assert "exactly one in-progress" in (result.error or "")
