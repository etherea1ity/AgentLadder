from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from klara.core.tools import ToolCall

MessageRole = Literal["user", "assistant", "tool"]


@dataclass(frozen=True)
class KlaraMessage:
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)

    def to_public_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.name is not None:
            data["name"] = self.name
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            data["tool_calls"] = [call.to_public_dict() for call in self.tool_calls]
        return data


@dataclass(frozen=True)
class ModelResponse:
    content: str
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    usage: dict[str, int] | None = None
