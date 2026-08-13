from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from klara.mcp import (
    McpClient,
    McpPermissionRequired,
    McpService,
    McpTransportKind,
    McpValidationError,
    SQLiteMcpRepository,
    StdioTransport,
)
from klara.permissions import (
    PermissionDecision,
    PermissionScope,
    PermissionService,
    SQLitePermissionRepository,
)
from klara.core.tools import ToolCall
from klara.tools.executor import ToolExecutor


class AllowAll:
    def __init__(self) -> None:
        self.actions = []

    def evaluate(self, *, scope, action):
        self.actions.append(action)
        return PermissionDecision(allowed=True, reason="test_allow", action=action)


def create_service(tmp_path, permission=None):
    permission = permission or AllowAll()
    service = McpService(
        SQLiteMcpRepository(tmp_path / "mcp.sqlite3"),
        permission,
        client_factory=lambda config: McpClient(StdioTransport(config), request_timeout_seconds=2),
    )
    return service, permission


def create_fixture(service, scope):
    return service.create_server(
        scope=scope,
        name="Fixture Server",
        transport=McpTransportKind.STDIO,
        command=sys.executable,
        args=(str(Path("tests/fixtures/mcp/stdio_server.py").resolve()),),
    )


def test_service_connects_catalogs_dynamic_tools_and_audits_without_content(tmp_path) -> None:
    service, permission = create_service(tmp_path)
    scope = PermissionScope("tenant-a", "owner-a", "klara")
    config = create_fixture(service, scope)
    state = service.connect(scope=scope, server_id=config.server_id)
    assert state.status.value == "connected"
    assert [item["name"] for item in state.catalog.tools] == ["echo", "slow"]

    dynamic = service.visible_tools(scope=scope)
    assert [item.spec.name for item in dynamic] == [
        "mcp__fixture_server__echo",
        "mcp__fixture_server__slow",
    ]
    projected = ToolExecutor([dynamic[0]]).execute(
        ToolCall("remote-call", dynamic[0].spec.name, {"message": "PRIVATE_DYNAMIC"})
    )
    assert "untrusted_external_mcp" in projected.content
    assert "PRIVATE_DYNAMIC" in projected.content
    assert projected.public_content == "[external MCP observation withheld from public trace]"
    assert "PRIVATE_DYNAMIC" not in json.dumps(projected.to_public_dict())
    result = service.call_tool(
        scope=scope,
        server_id=config.server_id,
        tool_name="echo",
        arguments={"message": "PRIVATE_TOOL_CONTENT"},
    )
    assert result["content"][0]["text"] == "PRIVATE_TOOL_CONTENT"
    resource = service.read_resource(
        scope=scope, server_id=config.server_id, uri="fixture://guide"
    )
    prompt = service.get_prompt(
        scope=scope, server_id=config.server_id, name="brief", arguments={}
    )
    assert resource["contents"][0]["text"] == "fixture resource"
    assert prompt["messages"][0]["role"] == "user"
    public = json.dumps(service.list_state(scope=scope), ensure_ascii=False)
    assert "PRIVATE_TOOL_CONTENT" not in public
    assert any(action.resource.startswith("mcp:") for action in permission.actions)
    service.disconnect(scope=scope, server_id=config.server_id)


def test_duplicate_dynamic_namespace_is_rejected_and_shutdown_closes_clients(tmp_path) -> None:
    service, _ = create_service(tmp_path)
    scope = PermissionScope("tenant-a", "owner-a", "klara")
    config = create_fixture(service, scope)
    with pytest.raises(McpValidationError, match="name_conflict"):
        service.create_server(
            scope=scope,
            name="fixture-server",
            transport=McpTransportKind.STREAMABLE_HTTP,
            endpoint="https://example.com/mcp",
        )
    service.connect(scope=scope, server_id=config.server_id)
    client = service._clients[config.server_id]
    service.shutdown()
    assert client.transport.process.poll() is not None
    assert service.list_state(scope=scope)["servers"][0]["connection"]["status"] == "disconnected"


def test_real_permission_engine_blocks_connect_and_creates_exact_request(tmp_path) -> None:
    permissions = PermissionService(SQLitePermissionRepository(tmp_path / "permissions.sqlite3"))
    service, _ = create_service(tmp_path, permissions)
    scope = PermissionScope("tenant-a", "owner-a", "klara")
    config = create_fixture(service, scope)
    with pytest.raises(McpPermissionRequired) as caught:
        service.connect(scope=scope, server_id=config.server_id)
    decision = caught.value.decision
    assert decision.request_id
    assert decision.action.resource == f"mcp:{config.server_id}/connect"
    assert service.list_state(scope=scope)["servers"][0]["connection"]["status"] == "disconnected"


def test_configuration_stores_only_credential_references_and_is_tenant_scoped(tmp_path) -> None:
    service, _permission = create_service(tmp_path)
    owner = PermissionScope("tenant-a", "owner-a", "klara")
    config = service.create_server(
        scope=owner,
        name="Remote",
        transport=McpTransportKind.STREAMABLE_HTTP,
        endpoint="https://example.com/mcp",
        credential_ref="MCP_REMOTE_TOKEN",
    )
    public = service.list_state(scope=owner)
    assert public["servers"][0]["config"]["credential_ref"] == "MCP_REMOTE_TOKEN"
    assert "env_refs" not in public["servers"][0]["config"]
    assert service.list_state(scope=PermissionScope("tenant-b", "owner-a", "klara"))["servers"] == []
    database = (tmp_path / "mcp.sqlite3").read_text(encoding="utf-8", errors="ignore")
    assert "Bearer " not in database
    assert "PRIVATE_TOKEN_VALUE" not in database
    assert config.endpoint == "https://example.com/mcp"


def test_configuration_rejects_raw_secret_arguments_and_endpoint_credentials(tmp_path) -> None:
    service, _ = create_service(tmp_path)
    scope = PermissionScope("tenant-a", "owner-a", "klara")
    with pytest.raises(McpValidationError, match="secrets_require_environment_reference"):
        service.create_server(
            scope=scope,
            name="Unsafe",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=("--api-key=PRIVATE_TOKEN_VALUE",),
        )
    with pytest.raises(McpValidationError, match="endpoint_invalid"):
        service.create_server(
            scope=scope,
            name="Unsafe URL",
            transport=McpTransportKind.STREAMABLE_HTTP,
            endpoint="https://user:password@example.com/mcp",
        )
