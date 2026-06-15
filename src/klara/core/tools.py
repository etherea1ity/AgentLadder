"""Tool request, result, and specification contracts for Klara core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A model-requested tool invocation.

    Core records the request but does not know whether the tool is RAG, memory,
    web, or a fake Chapter 1 capability. Concrete ability ownership stays in
    `klara.capabilities` and service layers.
    """

    # Id joins this request with the tool result observation.
    id: str
    # Name is resolved by ToolExecutor against currently visible tools.
    name: str
    # Arguments must stay JSON-compatible so traces and adapters can inspect them.
    arguments: JsonObject = field(default_factory=dict)

    def to_public_dict(self) -> JsonObject:
        """Serialize the tool request for trace and hook payloads.

        Returns:
            A JSON-compatible dictionary describing the requested call.
        """

        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass(frozen=True)
class ToolResult:
    """Runtime observation produced after executing a tool call.

    Successful and failed tools both return this shape so the loop can feed an
    observation back to the model instead of crashing on ordinary tool errors.
    """

    # Tool call id preserves the request/result join key.
    tool_call_id: str
    # Name records which tool produced the observation.
    name: str
    # Content is the model-visible observation body.
    content: str
    # Ok separates usable observations from error observations.
    ok: bool = True
    # Error carries public failure text when ok is false.
    error: str | None = None

    def to_public_dict(self) -> JsonObject:
        """Serialize the result for trace and hook payloads.

        Returns:
            A JSON-compatible dictionary describing the tool observation.
        """

        # Keep the public payload compact while preserving failure semantics.
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
    """Model-visible description of an available tool.

    The spec is what the harness exposes to the model. It is intentionally
    smaller than a concrete tool implementation.
    """

    # Name is the stable call target used by ToolCall.
    name: str
    # Description tells the model when the tool is useful.
    description: str
    # Input schema describes the expected JSON arguments.
    input_schema: JsonObject

    def to_public_dict(self) -> JsonObject:
        """Serialize the model-visible tool declaration.

        Returns:
            A JSON-compatible dictionary for LLM clients and traces.
        """

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class KlaraTool(Protocol):
    """Protocol implemented by concrete capabilities that core may execute."""

    spec: ToolSpec

    def execute(self, arguments: JsonObject) -> ToolResult:
        """Run the concrete capability with JSON-compatible arguments.

        Args:
            arguments: Tool-call arguments produced by the model.

        Returns:
            A model-visible tool observation.
        """

        ...
