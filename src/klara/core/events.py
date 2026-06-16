"""Lifecycle event contract emitted by Klara's core loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class KlaraEvent:
    """One traceable runtime event.

    Events are the bridge from core execution to hooks, trace files, future UI
    streaming, eval datasets, and policy-learning trajectories.
    """

    # Type names the lifecycle point, such as run.started or tool.completed.
    type: str
    # Run id joins all events from a single loop execution.
    run_id: str
    # Timestamp is created in UTC to keep trace ordering portable.
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    # Payload carries public event details; private prompt bodies stay out by default.
    payload: dict[str, Any] = field(default_factory=dict)
    # Schema version lets trace payloads evolve deliberately.
    schema_version: int = 1

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize the event for JSONL trace sinks.

        Returns:
            A JSON-compatible public event dictionary.
        """

        return {
            "schema_version": self.schema_version,
            "type": self.type,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
