"""Typed contracts for bounded subagents, persistent teams, and worktrees."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class AgentKind(StrEnum):
    ONE_SHOT = "one_shot"
    TEAMMATE = "teammate"


class AgentStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class MessageKind(StrEnum):
    TASK_ASSIGNMENT = "task_assignment"
    PROGRESS = "progress"
    QUESTION = "question"
    HANDOFF = "handoff"
    RESULT = "result"
    CANCEL = "cancel"


class WorktreeStatus(StrEnum):
    CREATING = "creating"
    READY = "ready"
    REMOVING = "removing"
    REMOVED = "removed"
    FAILED = "failed"


@dataclass(frozen=True)
class TeamScope:
    tenant_id: str
    owner_id: str
    team_id: str

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.owner_id.strip() or not self.team_id.strip():
            raise ValueError("team_scope_requires_tenant_owner_and_team")

    def to_public_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class TeamAgent:
    agent_id: str
    scope: TeamScope
    name: str
    role: str
    kind: AgentKind
    status: AgentStatus
    capability_names: tuple[str, ...]
    parent_agent_id: str | None = None
    parent_task_id: str | None = None
    child_task_id: str | None = None
    context_sha256: str | None = None
    summary: str | None = None
    summary_sha256: str | None = None
    error_code: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_owner_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.to_public_dict()
        value["kind"] = self.kind.value
        value["status"] = self.status.value
        value["capability_names"] = list(self.capability_names)
        return value

    def to_public_dict(self) -> dict[str, Any]:
        return self.to_owner_dict()


@dataclass(frozen=True)
class TeamMessage:
    message_id: str
    scope: TeamScope
    sender_id: str
    recipient_id: str
    kind: MessageKind
    body: str
    task_id: str | None
    sequence: int
    created_at: str
    acknowledged_at: str | None = None

    def to_owner_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.to_public_dict()
        value["kind"] = self.kind.value
        return value

    def to_public_dict(self) -> dict[str, Any]:
        return self.to_owner_dict()


@dataclass(frozen=True)
class WorktreeLease:
    worktree_id: str
    scope: TeamScope
    agent_id: str
    task_id: str
    branch_name: str
    base_ref: str
    path: str
    status: WorktreeStatus
    head_sha: str | None
    error_code: str | None
    created_at: str
    updated_at: str
    removed_at: str | None = None

    def to_owner_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.to_public_dict()
        value["status"] = self.status.value
        return value

    def to_public_dict(self) -> dict[str, Any]:
        return self.to_owner_dict()


@dataclass(frozen=True)
class OneShotRequest:
    title: str
    instructions: str
    capability_names: tuple[str, ...] = ()
    parent_task_id: str | None = None
    parent_agent_id: str = "klara"
    model: str | None = None


@dataclass(frozen=True)
class OneShotExecution:
    summary: str
    public_metrics: dict[str, int | float | str | bool] = field(default_factory=dict)


def new_team_id() -> str:
    return f"team_{uuid4().hex}"


def new_agent_id() -> str:
    return f"agent_{uuid4().hex}"


def new_team_message_id() -> str:
    return f"tmsg_{uuid4().hex}"


def new_worktree_id() -> str:
    return f"worktree_{uuid4().hex}"
