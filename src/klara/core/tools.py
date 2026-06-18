"""Tool request, result, and specification contracts for Klara core."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


JsonObject = dict[str, Any]


class ToolSideEffect(StrEnum):
    """Side-effect class used by the runtime to plan tool execution."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    CONTROL = "control"


class ToolOutputTrust(StrEnum):
    """Trust class for model-visible tool observations."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True)
class ToolMetadata:
    """Klara-visible metadata for planning and guarding a concrete tool.

    Tool metadata is not sent to the model. It gives the runtime enough
    information to decide whether a tool may run in parallel, whether it needs
    approval, how much output can be exposed, and whether the observation came
    from a trusted local source or untrusted external content.
    """

    # Label is human-facing and can be shown in trace/UI surfaces.
    label: str
    # Category groups tools without leaking package or teaching structure.
    category: str
    # Side effect tells the runtime how risky the tool is.
    side_effect: ToolSideEffect = ToolSideEffect.NONE
    # Parallel-safe tools may share an execution wave with other safe tools.
    parallel_safe: bool = True
    # Approval is reserved for mutating, control-plane, or high-risk tools.
    requires_approval: bool = False
    # Timeout is a per-tool execution budget for future executors/adapters.
    timeout_seconds: float = 10.0
    # Max output bounds the model-visible observation size.
    max_output_chars: int = 4000
    # Output trust lets later prompt wrappers treat web content as untrusted.
    output_trust: ToolOutputTrust = ToolOutputTrust.TRUSTED

    def __post_init__(self) -> None:
        """Validate runtime metadata when a concrete tool is declared."""

        if not self.label.strip():
            raise ValueError("tool metadata label must not be empty")
        if not self.category.strip():
            raise ValueError("tool metadata category must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("tool metadata timeout_seconds must be positive")
        if self.max_output_chars < 1:
            raise ValueError("tool metadata max_output_chars must be at least 1")


@dataclass(frozen=True)
class ToolCall:
    """A model-requested tool invocation.

    Core records the request but does not know whether the tool is RAG, memory,
    web, or a deterministic demonstration tool. Concrete tool ownership stays
    in `klara.tools` and service layers.
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
    """Protocol implemented by concrete tools that a runner may execute."""

    spec: ToolSpec
    metadata: ToolMetadata

    def execute(self, arguments: JsonObject) -> ToolResult:
        """Run the concrete capability with JSON-compatible arguments.

        Args:
            arguments: Tool-call arguments produced by the model.

        Returns:
            A model-visible tool observation.
        """

        ...


class ToolRunner(Protocol):
    """Protocol for the injected tool executor used by the loop."""

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        """Return model-visible tool specifications for this run."""

        ...

    def execute_many(self, calls: tuple[ToolCall, ...]) -> tuple[ToolResult, ...]:
        """Execute one assistant tool-call batch and preserve request order."""

        ...
