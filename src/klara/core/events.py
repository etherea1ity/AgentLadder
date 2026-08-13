"""Lifecycle event contract emitted by Klara's core loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class EventKind(StrEnum):
    """Stable public lifecycle event names emitted by Klara core."""

    RUN_STARTED = "run.started"
    USER_PROMPT_SUBMIT_STARTED = "user_prompt_submit.started"
    USER_PROMPT_SUBMIT_COMPLETED = "user_prompt_submit.completed"
    TURN_STARTED = "turn.started"
    LLM_STARTED = "llm.started"
    LLM_COMPLETED = "llm.completed"
    PRE_TOOL_USE_STARTED = "pre_tool_use.started"
    PRE_TOOL_USE_COMPLETED = "pre_tool_use.completed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    POST_TOOL_USE_STARTED = "post_tool_use.started"
    POST_TOOL_USE_COMPLETED = "post_tool_use.completed"
    PREPARE_NEXT_TURN_STARTED = "prepare_next_turn.started"
    PREPARE_NEXT_TURN_COMPLETED = "prepare_next_turn.completed"
    PRE_COMPACT_STARTED = "pre_compact.started"
    PRE_COMPACT_COMPLETED = "pre_compact.completed"
    TURN_COMPLETED = "turn.completed"
    TOOL_POLICY_STOPPED = "tool_policy.stopped"
    STOP_STARTED = "stop.started"
    STOP_COMPLETED = "stop.completed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


class EventSequencer:
    """Assign monotonic sequence numbers within one Klara run."""

    def __init__(self) -> None:
        """Create a sequencer whose first emitted value is one."""

        self._next_value = 1

    def next(self) -> int:
        """Return the next sequence number for a run-local event.

        Returns:
            A monotonically increasing integer starting at one.
        """

        value = self._next_value
        self._next_value += 1
        return value


@dataclass(frozen=True)
class KlaraEvent:
    """One traceable runtime event.

    Events are the bridge from core execution to hooks, trace files, future UI
    streaming, eval datasets, and policy-learning trajectories.
    """

    # Type names the lifecycle point, such as run.started or tool.completed.
    type: str | EventKind
    # Run id joins all events from a single loop execution.
    run_id: str
    # Timestamp is created in UTC to keep trace ordering portable.
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    # Payload stays available for older observers and mirrors public_payload.
    payload: dict[str, Any] = field(default_factory=dict)
    # Schema version lets trace payloads evolve deliberately.
    schema_version: int = 1
    # Event id gives replay, API projection, and tests a stable join key.
    event_id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    # Sequence number orders events inside one run when supplied by the loop.
    seq: int | None = None
    # Public payload is safe for trace, API projection, and frontend surfaces.
    public_payload: dict[str, Any] | None = None
    # Private content is never embedded; this optional ref is future-facing.
    private_payload_ref: str | None = None
    # Span fields are reserved for future nested lifecycle projections.
    span_id: str | None = None
    parent_span_id: str | None = None

    def __post_init__(self) -> None:
        """Normalize event kind and keep payload compatibility fields aligned."""

        event_type = self.type.value if isinstance(self.type, EventKind) else str(self.type)
        object.__setattr__(self, "type", event_type)
        if self.public_payload is None:
            object.__setattr__(self, "public_payload", dict(self.payload))
            return
        object.__setattr__(self, "payload", dict(self.public_payload))

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize the event for JSONL trace sinks.

        Returns:
            A JSON-compatible public event dictionary.
        """

        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "seq": self.seq,
            "type": self.type,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "payload": self.public_payload or {},
            **(
                {"private_payload_ref": self.private_payload_ref}
                if self.private_payload_ref
                else {}
            ),
        }
