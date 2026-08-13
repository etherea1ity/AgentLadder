"""Validated, deterministic current-session todo planning state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TodoStatus = Literal["pending", "in_progress", "completed"]
TodoOperation = Literal["replace", "merge"]
MAX_TODO_ITEMS = 24


class TodoItem(BaseModel):
    """One public plan step with a stable id and explicit state."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")
    title: str = Field(min_length=1, max_length=160)
    status: TodoStatus = "pending"

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = " ".join(value.split())
        if not title:
            raise ValueError("todo title must not be empty")
        return title


class TodoPlan(BaseModel):
    """Versioned session plan whose one-active-item rule cannot be bypassed."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["klara.todo-plan.v1"] = "klara.todo-plan.v1"
    session_id: str
    version: int = Field(ge=1)
    items: list[TodoItem] = Field(max_length=MAX_TODO_ITEMS)
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @model_validator(mode="after")
    def validate_plan(self) -> "TodoPlan":
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("todo item ids must be unique")
        active = sum(item.status == "in_progress" for item in self.items)
        if active > 1:
            raise ValueError("todo plan allows at most one in-progress item")
        return self


def apply_todo_update(
    *,
    session_id: str,
    existing: TodoPlan | None,
    operation: TodoOperation,
    items: Sequence[TodoItem],
) -> TodoPlan:
    """Apply replace or ordered upsert semantics and increment the version."""

    if existing is not None and existing.session_id != session_id:
        raise ValueError("todo plan session mismatch")
    if operation == "replace":
        next_items = list(items)
    else:
        next_items = list(existing.items if existing else [])
        positions = {item.id: index for index, item in enumerate(next_items)}
        for item in items:
            if item.id in positions:
                next_items[positions[item.id]] = item
            else:
                positions[item.id] = len(next_items)
                next_items.append(item)
    return TodoPlan(
        session_id=session_id,
        version=(existing.version + 1 if existing else 1),
        items=next_items,
    )
