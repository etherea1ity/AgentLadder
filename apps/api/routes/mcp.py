"""Owner-scoped MCP configuration, lifecycle, catalog, and audit API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from apps.api.dependencies import get_mcp_service, get_permission_scope
from klara.mcp import (
    McpError,
    McpNotFoundError,
    McpPermissionRequired,
    McpService,
    McpTransportKind,
    McpValidationError,
)
from klara.permissions import PermissionScope


router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class CreateMcpServerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    transport: McpTransportKind
    command: str | None = Field(default=None, max_length=1024)
    args: list[str] = Field(default_factory=list, max_length=32)
    endpoint: str | None = Field(default=None, max_length=2048)
    credential_ref: str | None = Field(default=None, max_length=160)
    env_refs: dict[str, str] = Field(default_factory=dict)


class McpToolCallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    arguments: dict[str, object] = Field(default_factory=dict)


class McpResourceReadRequest(BaseModel):
    uri: str = Field(min_length=1, max_length=4096)


class McpPromptGetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    arguments: dict[str, str] = Field(default_factory=dict)


@router.get("")
def mcp_state(
    service: McpService = Depends(get_mcp_service),
    scope: PermissionScope = Depends(get_permission_scope),
):
    return service.list_state(scope=scope)


@router.post("", status_code=201)
def create_mcp_server(
    request: CreateMcpServerRequest,
    service: McpService = Depends(get_mcp_service),
    scope: PermissionScope = Depends(get_permission_scope),
):
    try:
        config = service.create_server(
            scope=scope,
            name=request.name,
            transport=request.transport,
            command=request.command,
            args=tuple(request.args),
            endpoint=request.endpoint,
            credential_ref=request.credential_ref,
            env_refs=request.env_refs,
        )
        return {"schema_version": "klara.mcp-server.v1", "config": config.to_owner_dict()}
    except McpValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/{server_id}/tools/call")
def call_mcp_tool(server_id: str, request: McpToolCallRequest, service: McpService = Depends(get_mcp_service), scope: PermissionScope = Depends(get_permission_scope)):
    return _execute(lambda: service.call_tool(scope=scope, server_id=server_id, tool_name=request.name, arguments=request.arguments))


@router.post("/{server_id}/resources/read")
def read_mcp_resource(server_id: str, request: McpResourceReadRequest, service: McpService = Depends(get_mcp_service), scope: PermissionScope = Depends(get_permission_scope)):
    return _execute(lambda: service.read_resource(scope=scope, server_id=server_id, uri=request.uri))


@router.post("/{server_id}/prompts/get")
def get_mcp_prompt(server_id: str, request: McpPromptGetRequest, service: McpService = Depends(get_mcp_service), scope: PermissionScope = Depends(get_permission_scope)):
    return _execute(lambda: service.get_prompt(scope=scope, server_id=server_id, name=request.name, arguments=request.arguments))


@router.post("/{server_id}/{action}")
def transition_mcp_server(server_id: str, action: str, service: McpService = Depends(get_mcp_service), scope: PermissionScope = Depends(get_permission_scope)):
    if action == "connect":
        return _execute(lambda: service.connect(scope=scope, server_id=server_id))
    if action == "reconnect":
        return _execute(lambda: service.reconnect(scope=scope, server_id=server_id))
    if action == "disconnect":
        return _execute(lambda: service.disconnect(scope=scope, server_id=server_id))
    if action == "ping":
        return _execute(lambda: service.ping(scope=scope, server_id=server_id))
    if action == "delete":
        return _execute(lambda: {"deleted": service.delete_server(scope=scope, server_id=server_id)})
    raise HTTPException(status_code=404, detail="mcp_action_not_found")


def _execute(callback):
    try:
        result = callback()
        if hasattr(result, "to_public_dict"):
            return result.to_public_dict()
        return result
    except McpPermissionRequired as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "code": exc.decision.reason,
                "permission": exc.decision.to_public_dict(),
            },
        ) from None
    except McpNotFoundError:
        raise HTTPException(status_code=404, detail="mcp_server_not_found") from None
    except (McpValidationError, McpError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
