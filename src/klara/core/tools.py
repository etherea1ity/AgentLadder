from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: JsonObject = field(default_factory=dict)

    def to_public_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    ok: bool = True
    error: str | None = None

    def to_public_dict(self) -> JsonObject:
        data: JsonObject = {
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": self.content,
            "ok": self.ok,
        }
        if self.error is not None:
            data["error"] = self.error
        return data


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: JsonObject

    def to_public_dict(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class KlaraTool(Protocol):
    spec: ToolSpec

    def execute(self, arguments: JsonObject) -> ToolResult:
        ...
