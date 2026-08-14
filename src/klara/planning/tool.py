"""Model-callable todo_write tool bound to one current session."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

from klara.core.tools import (
    JsonObject,
    ToolMetadata,
    ToolResult,
    ToolSideEffect,
    ToolSpec,
)
from klara.planning.todo import TodoItem, TodoOperation, TodoPlan
from klara.tools.base import BaseTool


class TodoPlanStore(Protocol):
    def update_todo_plan(
        self,
        session_id: str,
        operation: TodoOperation,
        items: list[TodoItem],
    ) -> TodoPlan: ...


@dataclass(frozen=True)
class TodoWriteTool(BaseTool):
    """Replace or merge the current session's visible plan."""

    session_id: str
    store: TodoPlanStore
    spec: ToolSpec = ToolSpec(
        name="todo_write",
        description="Create or update the current session plan for multi-step work. Do not plan simple answers. Use the minimum set of distinct, non-overlapping steps that covers the user's explicit goals; do not split discovery, fixing, and re-verification into separate steps unless the user asks. A non-empty unfinished replacement plan must have exactly one item in_progress (normally the first actionable item); keep every other unfinished item pending and mark verified work completed.",
        input_schema={
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["replace", "merge"]},
                "items": {
                    "type": "array",
                    "maxItems": 24,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "pattern": "^[a-z0-9][a-z0-9_-]{0,47}$",
                                "maxLength": 48,
                            },
                            "title": {"type": "string", "minLength": 1, "maxLength": 160},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}
                        },
                        "required": ["id", "title", "status"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["operation", "items"],
            "additionalProperties": False
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Update plan",
        category="planning",
        side_effect=ToolSideEffect.WRITE,
        parallel_safe=False,
        max_output_chars=12000,
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        operation = arguments.get("operation")
        if operation not in {"replace", "merge"}:
            return self.failure(arguments, "operation must be replace or merge")
        raw_items = arguments.get("items")
        if not isinstance(raw_items, list):
            return self.failure(arguments, "items must be an array")
        try:
            items = [TodoItem.model_validate(item) for item in raw_items]
            if operation == "replace" and any(
                item.status != "completed" for item in items
            ) and sum(item.status == "in_progress" for item in items) != 1:
                return self.failure(
                    arguments,
                    "unfinished replacement plan requires exactly one in-progress item",
                )
            plan = self.store.update_todo_plan(
                self.session_id,
                operation=operation,
                items=items,
            )
        except ValueError as exc:
            return self.failure(arguments, str(exc))
        return self.success(arguments, json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")))
