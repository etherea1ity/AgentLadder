"""Typed, tenant-scoped permission contracts for AgentLadder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from klara.core.tools import ToolSideEffect


def utc_now_iso() -> str:
    """Return a sortable timezone-aware UTC timestamp."""

    return datetime.now(UTC).isoformat()


class PermissionRisk(StrEnum):
    """Closed set of action-risk levels understood by policy."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionEffect(StrEnum):
    """User decisions supported by the product permission surface."""

    DENY = "deny"
    ALLOW_ONCE = "allow_once"
    ALLOW_TASK = "allow_task"
    ALLOW_STANDING = "allow_standing"


class PermissionRequestStatus(StrEnum):
    """Lifecycle state for an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class PermissionGrantStatus(StrEnum):
    """Lifecycle state for an allow or deny grant."""

    ACTIVE = "active"
    CONSUMED = "consumed"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass(frozen=True)
class PermissionScope:
    """Identity and task partition carried by every decision."""

    tenant_id: str
    actor_id: str
    agent_id: str
    task_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.actor_id.strip() or not self.agent_id.strip():
            raise ValueError("permission_scope_requires_tenant_actor_and_agent")

    def to_public_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class PermissionAction:
    """Canonical action evaluated independently from model prose."""

    tool_name: str
    capability: str
    side_effect: ToolSideEffect
    resource_type: str
    resource: str
    risk: PermissionRisk
    destructive: bool
    externally_consequential: bool
    arguments_sha256: str

    def __post_init__(self) -> None:
        if not self.tool_name.strip() or not self.capability.strip():
            raise ValueError("permission_action_requires_known_capability")
        if not self.resource_type.strip() or not self.resource.strip():
            raise ValueError("permission_action_requires_known_resource")
        if len(self.arguments_sha256) != 64:
            raise ValueError("permission_action_requires_argument_hash")

    def to_public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["side_effect"] = self.side_effect.value
        value["risk"] = self.risk.value
        return value


@dataclass(frozen=True)
class PermissionRequest:
    """Durable, deduplicated request for explicit user authority."""

    request_id: str
    fingerprint: str
    scope: PermissionScope
    action: PermissionAction
    status: PermissionRequestStatus
    created_at: str
    updated_at: str
    expires_at: str
    repeated_count: int = 1
    decision_effect: PermissionEffect | None = None

    def to_owner_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.to_public_dict()
        value["action"] = self.action.to_public_dict()
        value["status"] = self.status.value
        value["decision_effect"] = (
            self.decision_effect.value if self.decision_effect is not None else None
        )
        return value


@dataclass(frozen=True)
class PermissionGrant:
    """Durable scoped authority or denial created from a user decision."""

    grant_id: str
    request_id: str | None
    effect: PermissionEffect
    status: PermissionGrantStatus
    scope: PermissionScope
    action: PermissionAction
    created_at: str
    expires_at: str
    remaining_uses: int | None = None
    parent_grant_id: str | None = None
    revoked_at: str | None = None

    def to_owner_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["effect"] = self.effect.value
        value["status"] = self.status.value
        value["scope"] = self.scope.to_public_dict()
        value["action"] = self.action.to_public_dict()
        return value


@dataclass(frozen=True)
class PermissionAuditEvent:
    """Immutable content-free decision audit record."""

    audit_id: str
    tenant_id: str
    actor_id: str
    agent_id: str
    task_id: str | None
    operation: str
    decision: str
    occurred_at: str
    request_id: str | None = None
    grant_id: str | None = None
    tool_name: str | None = None
    capability: str | None = None
    resource_type: str | None = None
    resource: str | None = None
    arguments_sha256: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_owner_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PermissionDecision:
    """One fail-closed runtime decision returned to the permission hook."""

    allowed: bool
    reason: str
    action: PermissionAction | None = None
    request_id: str | None = None
    grant_id: str | None = None
    effect: PermissionEffect | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "klara.permission-decision.v1",
            "allowed": self.allowed,
            "reason": self.reason,
            "request_id": self.request_id,
            "grant_id": self.grant_id,
            "effect": self.effect.value if self.effect is not None else None,
            "action": self.action.to_public_dict() if self.action is not None else None,
        }


def new_permission_request_id() -> str:
    return f"preq_{uuid4().hex}"


def new_permission_grant_id() -> str:
    return f"pgrant_{uuid4().hex}"


def new_permission_audit_id() -> str:
    return f"paudit_{uuid4().hex}"
