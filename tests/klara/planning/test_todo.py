from __future__ import annotations

import pytest
from pydantic import ValidationError

from klara.planning.todo import MAX_TODO_ITEMS, TodoItem, TodoPlan, apply_todo_update


def item(item_id: str, status: str = "pending", title: str | None = None) -> TodoItem:
    return TodoItem(id=item_id, title=title or item_id.replace("-", " "), status=status)


def test_replace_normalizes_titles_and_versions_the_plan() -> None:
    first = apply_todo_update(
        session_id="sess-1",
        existing=None,
        operation="replace",
        items=[item("inspect", "in_progress", "  Inspect   repository  "), item("test")],
    )
    second = apply_todo_update(
        session_id="sess-1",
        existing=first,
        operation="replace",
        items=[item("document", "pending")],
    )

    assert first.version == 1
    assert [entry.title for entry in first.items] == ["Inspect repository", "test"]
    assert second.version == 2
    assert [entry.id for entry in second.items] == ["document"]


def test_merge_is_an_ordered_upsert_and_does_not_reorder_existing_items() -> None:
    existing = TodoPlan(
        session_id="sess-1",
        version=4,
        items=[item("inspect", "completed"), item("build", "in_progress")],
    )

    merged = apply_todo_update(
        session_id="sess-1",
        existing=existing,
        operation="merge",
        items=[item("build", "completed", "Build runtime"), item("verify", "in_progress")],
    )

    assert merged.version == 5
    assert [(entry.id, entry.status) for entry in merged.items] == [
        ("inspect", "completed"),
        ("build", "completed"),
        ("verify", "in_progress"),
    ]


def test_plan_rejects_duplicate_ids_multiple_active_items_and_oversize() -> None:
    with pytest.raises(ValidationError, match="unique"):
        TodoPlan(session_id="sess-1", version=1, items=[item("same"), item("same")])
    with pytest.raises(ValidationError, match="at most one"):
        TodoPlan(
            session_id="sess-1",
            version=1,
            items=[item("first", "in_progress"), item("second", "in_progress")],
        )
    with pytest.raises(ValidationError):
        TodoPlan(
            session_id="sess-1",
            version=1,
            items=[item(f"step-{index}") for index in range(MAX_TODO_ITEMS + 1)],
        )


def test_update_rejects_cross_session_state() -> None:
    existing = TodoPlan(session_id="sess-1", version=1, items=[])

    with pytest.raises(ValueError, match="session mismatch"):
        apply_todo_update(
            session_id="sess-2",
            existing=existing,
            operation="merge",
            items=[],
        )
