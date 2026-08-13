"""Typed contracts for Klara's tenant-scoped durable task state machine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class TaskState(StrEnum):
    WAITING = "waiting"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptOutcome(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PAUSED = "paused"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class TaskScope:
    tenant_id: str
    owner_id: str
    agent_id: str = "klara"

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.owner_id.strip() or not self.agent_id.strip():
            raise ValueError("task_scope_requires_tenant_owner_and_agent")

    def to_public_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DurableTask:
    task_id: str
    scope: TaskScope
    title: str
    description: str
    state: TaskState
    dependency_ids: tuple[str, ...] = ()
    parent_task_id: str | None = None
    required_artifacts: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    active_attempt_id: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    progress: int = 0
    current_step: str | None = None
    block_reason: str | None = None
    lease_worker_id: str | None = None
    lease_token_sha256: str | None = None
    lease_expires_at: str | None = None
    heartbeat_at: str | None = None
    checkpoint_sequence: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None
    cancelled_at: str | None = None

    def to_owner_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.to_public_dict()
        value["state"] = self.state.value
        return value

    def to_public_dict(self) -> dict[str, Any]:
        value = self.to_owner_dict()
        value.pop("lease_token_sha256", None)
        return value


@dataclass(frozen=True)
class TaskAttempt:
    attempt_id: str
    task_id: str
    number: int
    worker_id: str
    outcome: AttemptOutcome
    started_at: str
    ended_at: str | None = None
    last_heartbeat_at: str | None = None
    lease_expires_at: str | None = None
    restored_checkpoint_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["outcome"] = self.outcome.value
        return value


@dataclass(frozen=True)
class TaskCheckpoint:
    checkpoint_id: str
    task_id: str
    attempt_id: str
    sequence: int
    summary: str
    payload_sha256: str
    payload_keys: tuple[str, ...]
    created_at: str

    def to_owner_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["payload_field_count"] = len(self.payload_keys)
        value.pop("payload_keys", None)
        return value


@dataclass(frozen=True)
class TaskArtifact:
    artifact_id: str
    task_id: str
    name: str
    uri: str
    media_type: str
    sha256: str
    is_evidence: bool
    attempt_id: str
    created_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskEvent:
    event_id: str
    task_id: str
    operation: str
    from_state: str | None
    to_state: str
    occurred_at: str
    attempt_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskClaim:
    task: DurableTask
    lease_token: str
    restored_checkpoint: TaskCheckpoint | None

    def to_owner_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_public_dict(),
            "lease_token": self.lease_token,
            "restored_checkpoint": (
                self.restored_checkpoint.to_public_dict()
                if self.restored_checkpoint is not None
                else None
            ),
        }


@dataclass(frozen=True)
class EffectReservation:
    task_id: str
    idempotency_key: str
    attempt_id: str
    status: str
    should_execute: bool
    result_sha256: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_task_id() -> str:
    return f"task_{uuid4().hex}"


def new_attempt_id() -> str:
    return f"attempt_{uuid4().hex}"


def new_checkpoint_id() -> str:
    return f"checkpoint_{uuid4().hex}"


def new_artifact_id() -> str:
    return f"artifact_{uuid4().hex}"


def new_event_id() -> str:
    return f"tevent_{uuid4().hex}"
