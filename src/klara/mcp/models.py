"""Typed, tenant-scoped MCP connection and catalog contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from klara.permissions import PermissionScope


class McpTransportKind(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class McpServerStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True)
class McpServerConfig:
    server_id: str
    scope: PermissionScope
    name: str
    transport: McpTransportKind
    command: str | None = None
    args: tuple[str, ...] = ()
    endpoint: str | None = None
    credential_ref: str | None = None
    env_refs: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def to_owner_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.to_public_dict()
        value["transport"] = self.transport.value
        value["credential_ref"] = self.credential_ref
        value["env_ref_names"] = sorted(self.env_refs)
        value.pop("env_refs", None)
        return value


@dataclass(frozen=True)
class McpCapabilityCatalog:
    protocol_version: str
    server_name: str
    server_version: str
    capabilities: dict[str, Any]
    tools: tuple[dict[str, Any], ...] = ()
    resources: tuple[dict[str, Any], ...] = ()
    prompts: tuple[dict[str, Any], ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpConnectionState:
    server_id: str
    status: McpServerStatus
    connected_at: str | None = None
    last_checked_at: str | None = None
    last_error: str | None = None
    reconnect_count: int = 0
    catalog: McpCapabilityCatalog | None = None

    def to_public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["catalog"] = self.catalog.to_public_dict() if self.catalog else None
        return value


@dataclass(frozen=True)
class McpAuditEvent:
    event_id: str
    server_id: str
    tenant_id: str
    actor_id: str
    operation: str
    outcome: str
    occurred_at: str
    target: str | None = None
    duration_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_mcp_server_id() -> str:
    return f"mcp_server_{uuid4().hex}"


def new_mcp_audit_id() -> str:
    return f"mcp_audit_{uuid4().hex}"
