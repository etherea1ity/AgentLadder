from __future__ import annotations

from pathlib import Path
import sys

from fastapi import HTTPException
import pytest

from apps.api.main import app
from apps.api.routes.mcp import (
    CreateMcpServerRequest,
    create_mcp_server,
    mcp_state,
    transition_mcp_server,
)
from klara.mcp import McpClient, McpService, McpTransportKind, SQLiteMcpRepository, StdioTransport
from klara.permissions import PermissionEffect, PermissionScope, PermissionService, SQLitePermissionRepository


def test_mcp_api_requires_exact_approval_then_connects_and_projects_catalog(tmp_path) -> None:
    permissions = PermissionService(SQLitePermissionRepository(tmp_path / "permissions.sqlite3"))
    service = McpService(
        SQLiteMcpRepository(tmp_path / "mcp.sqlite3"),
        permissions,
        client_factory=lambda config: McpClient(StdioTransport(config), request_timeout_seconds=2),
    )
    scope = PermissionScope("tenant-test", "user-test", "klara")
    fixture = str(Path("tests/fixtures/mcp/stdio_server.py").resolve())
    created = create_mcp_server(
        CreateMcpServerRequest(
            name="Fixture server",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=[fixture],
        ),
        service,
        scope,
    )
    server_id = created["config"]["server_id"]
    assert "/api/mcp" in {route.path for route in app.routes}
    with pytest.raises(HTTPException) as caught:
        transition_mcp_server(server_id, "connect", service, scope)
    assert caught.value.status_code == 403
    request_id = caught.value.detail["permission"]["request_id"]
    permissions.decide_request(
        scope=scope,
        request_id=request_id,
        effect=PermissionEffect.ALLOW_STANDING,
        expires_seconds=300,
    )
    connected = transition_mcp_server(server_id, "connect", service, scope)
    assert connected["status"] == "connected"
    assert connected["catalog"]["tools"][0]["name"] == "echo"
    assert mcp_state(service, scope)["schema_version"] == "klara.mcp-state.v1"
    service.shutdown()


def test_mcp_api_hides_other_owner_and_rejects_unknown_action(tmp_path) -> None:
    permissions = PermissionService(SQLitePermissionRepository(tmp_path / "permissions.sqlite3"))
    service = McpService(SQLiteMcpRepository(tmp_path / "mcp.sqlite3"), permissions)
    owner = PermissionScope("tenant-a", "owner-a", "klara")
    create_mcp_server(
        CreateMcpServerRequest(
            name="Remote",
            transport=McpTransportKind.STREAMABLE_HTTP,
            endpoint="https://example.com/mcp",
            credential_ref="MCP_REMOTE_TOKEN",
        ),
        service,
        owner,
    )
    outsider = PermissionScope("tenant-b", "owner-a", "klara")
    assert mcp_state(service, outsider)["servers"] == []
    with pytest.raises(HTTPException) as caught:
        transition_mcp_server("missing", "invented", service, owner)
    assert caught.value.status_code == 404
