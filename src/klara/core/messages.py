"""Message and model-response contracts visible to Klara's loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from klara.core.tools import ToolCall

MessageRole = Literal["user", "assistant", "tool"]
ModelStreamEventType = Literal[
    "provider_reasoning_delta",
    "assistant_output_delta",
    "tool_call_delta",
    "completed",
    "failed",
]


@dataclass(frozen=True)
class KlaraMessage:
    """One model-visible message in the loop transcript.

    The core loop only understands a transcript of user, assistant, and tool
    messages. It does not know memory stores, RAG evidence packs, or UI state.
    Later layers must translate their state into this contract before the model
    sees it.
    """

    # Role controls how the message participates in the model-visible transcript.
    role: MessageRole
    # Content is the public text or observation body visible to the next turn.
    content: str
    # Name identifies tool messages without teaching core about concrete tools.
    name: str | None = None
    # Tool call id joins an assistant tool request with the resulting observation.
    tool_call_id: str | None = None
    # Assistant messages may carry one or more requested tool calls.
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize the message into a trace-safe public dictionary.

        Returns:
            A JSON-compatible dictionary that omits absent optional fields.
        """

        # Start with the stable fields every message must expose.
        data: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        # Add optional identifiers only when they are meaningful for this role.
        if self.name is not None:
            data["name"] = self.name
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            data["tool_calls"] = [call.to_public_dict() for call in self.tool_calls]
        return data


@dataclass(frozen=True)
class ModelResponse:
    """Assistant output returned by an injected LLM client.

    A model response can either end the loop with content or ask the runtime to
    execute tool calls. The LLM client is injected, so core never depends on a
    concrete provider.
    """

    # Content is the assistant text for the current turn.
    content: str
    # Tool calls request runtime work before the next model turn.
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    # Usage stays optional because fake LLMs and some providers may omit it.
    usage: dict[str, int] | None = None
    # Optional provider-visible reasoning summary for UI only, never history.
    reasoning_summary: str | None = None
    # Structured provider reasoning items are reserved for streaming adapters.
    reasoning_items: tuple[dict[str, object], ...] = field(default_factory=tuple)
    # Provider/model field that produced the public reasoning summary.
    reasoning_source: str | None = None


@dataclass(frozen=True)
class ModelStreamEvent:
    """Optional provider stream event reserved for future live reasoning UI."""

    type: ModelStreamEventType
    delta: str = ""
    payload: dict[str, object] = field(default_factory=dict)
    response: ModelResponse | None = None
