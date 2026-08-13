from __future__ import annotations

from dataclasses import replace

from apps.api.main import app
from apps.api.routes.permissions import decide_permission_request, list_permissions, revoke_permission_grant
from apps.api.schemas import PermissionDecisionRequest
from klara.core.tools import ToolCall, ToolMetadata, ToolSideEffect
from klara.permissions import PermissionActionResolver, PermissionScope, PermissionService, SQLitePermissionRepository


def test_permissions_api_decides_and_revokes_owner_request(tmp_path) -> None:
    service = PermissionService(SQLitePermissionRepository(tmp_path / "permissions.sqlite3"))
    scope = PermissionScope("tenant-test", "user-test", "klara", "session-test")
    resolver = PermissionActionResolver({"web_fetch": ToolMetadata(label="Fetch", category="web", side_effect=ToolSideEffect.NETWORK)}, tmp_path)
    decision = service.evaluate(scope=scope, action=resolver.resolve(ToolCall("fetch", "web_fetch", {"url": "https://example.com/docs"})))
    paths = {route.path for route in app.routes}
    assert "/api/permissions" in paths
    assert "/api/permissions/requests/{request_id}/decision" in paths
    owner_scope = replace(scope, task_id=None)
    grant = decide_permission_request(decision.request_id or "", PermissionDecisionRequest(effect="allow_once", expires_seconds=300), service, owner_scope)
    assert grant["effect"] == "allow_once"
    state = list_permissions(service, owner_scope)
    assert len(state["requests"]) == 1
    assert len(state["grants"]) == 1
    assert revoke_permission_grant(grant["grant_id"], service, owner_scope)["status"] == "revoked"
