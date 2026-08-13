from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from klara.core.tools import ToolCall, ToolMetadata, ToolSideEffect
from klara.permissions import (
    PermissionActionResolver,
    PermissionEffect,
    PermissionGrantStatus,
    PermissionNotFoundError,
    PermissionResolutionError,
    PermissionScope,
    PermissionService,
    PermissionValidationError,
    SQLitePermissionRepository,
)


def _runtime(tmp_path: Path):
    metadata = {
        "current_time": ToolMetadata(label="Clock", category="time"),
        "web_fetch": ToolMetadata(label="Fetch", category="web", side_effect=ToolSideEffect.NETWORK),
        "image_generate": ToolMetadata(label="Image", category="media", side_effect=ToolSideEffect.NETWORK),
        "memory_delete": ToolMetadata(label="Delete", category="memory", side_effect=ToolSideEffect.WRITE),
        "file_read": ToolMetadata(label="Read", category="file", side_effect=ToolSideEffect.READ),
        "sensitive_read": ToolMetadata(label="Sensitive", category="file", side_effect=ToolSideEffect.READ, requires_approval=True),
        "shell_command": ToolMetadata(label="Shell", category="shell", side_effect=ToolSideEffect.CONTROL),
        "mcp__github__create_issue": ToolMetadata(label="MCP", category="mcp", side_effect=ToolSideEffect.CONTROL),
    }
    repository = SQLitePermissionRepository(tmp_path / "permissions.sqlite3")
    service = PermissionService(repository)
    resolver = PermissionActionResolver(metadata, tmp_path)
    scope = PermissionScope("tenant-a", "user-a", "agent-a", "task-a")
    return service, resolver, scope


def test_low_risk_local_read_is_policy_allowed(tmp_path: Path) -> None:
    service, resolver, scope = _runtime(tmp_path)
    action = resolver.resolve(ToolCall("clock", "current_time", {"timezone": "UTC"}))
    decision = service.evaluate(scope=scope, action=action)
    assert decision.allowed is True
    assert decision.reason == "permission_low_risk_policy"
    assert service.list_state(scope=scope)["requests"] == []


def test_external_action_is_blocked_deduplicated_then_allowed_once(tmp_path: Path) -> None:
    service, resolver, scope = _runtime(tmp_path)
    action = resolver.resolve(ToolCall("fetch", "web_fetch", {"url": "HTTPS://Example.COM/a/../docs?token=secret"}))
    first = service.evaluate(scope=scope, action=action)
    second = service.evaluate(scope=scope, action=action)
    assert first.allowed is second.allowed is False
    assert first.request_id == second.request_id
    state = service.list_state(scope=scope)
    assert len(state["requests"]) == 1
    assert state["requests"][0]["repeated_count"] == 2
    assert state["requests"][0]["action"]["resource"] == "https://example.com/docs"
    assert "secret" not in str(state)
    grant = service.decide_request(scope=scope, request_id=first.request_id or "", effect=PermissionEffect.ALLOW_ONCE, expires_seconds=300)
    assert service.evaluate(scope=scope, action=action).allowed is True
    assert service.repository.get_grant(replace(scope, task_id=None), grant.grant_id).status is PermissionGrantStatus.CONSUMED
    assert service.evaluate(scope=scope, action=action).allowed is False


def test_deny_revoke_expiry_and_cross_tenant_isolation(tmp_path: Path) -> None:
    service, resolver, scope = _runtime(tmp_path)
    action = resolver.resolve(ToolCall("image", "image_generate", {"prompt": "cat"}))
    request = service.evaluate(scope=scope, action=action)
    denial = service.decide_request(scope=scope, request_id=request.request_id or "", effect=PermissionEffect.DENY, expires_seconds=300)
    owner_scope = replace(scope, task_id=None)
    assert service.evaluate(scope=scope, action=action).reason == "permission_denied"
    with pytest.raises(PermissionNotFoundError):
        service.revoke_grant(scope=PermissionScope("tenant-b", "user-a", "agent-a"), grant_id=denial.grant_id)
    assert service.revoke_grant(scope=owner_scope, grant_id=denial.grant_id).status is PermissionGrantStatus.REVOKED
    next_request = service.evaluate(scope=scope, action=action)
    grant = service.decide_request(scope=scope, request_id=next_request.request_id or "", effect=PermissionEffect.ALLOW_STANDING, expires_seconds=300)
    expired = replace(grant, expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat())
    service.repository.save_grant(expired)
    assert service.evaluate(scope=scope, action=action).allowed is False
    assert service.repository.get_grant(owner_scope, grant.grant_id).status is PermissionGrantStatus.EXPIRED


def test_allow_once_is_atomic_under_concurrency(tmp_path: Path) -> None:
    service, resolver, scope = _runtime(tmp_path)
    action = resolver.resolve(ToolCall("fetch", "web_fetch", {"url": "https://example.com"}))
    request = service.evaluate(scope=scope, action=action)
    service.decide_request(scope=scope, request_id=request.request_id or "", effect=PermissionEffect.ALLOW_ONCE, expires_seconds=300)
    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(lambda _: service.evaluate(scope=scope, action=action), range(2)))
    assert sum(decision.allowed for decision in decisions) == 1


def test_parent_to_child_authority_can_only_attenuate(tmp_path: Path) -> None:
    service, resolver, scope = _runtime(tmp_path)
    action = resolver.resolve(ToolCall("fetch", "web_fetch", {"url": "https://example.com/docs"}))
    request = service.evaluate(scope=scope, action=action)
    parent = service.decide_request(scope=scope, request_id=request.request_id or "", effect=PermissionEffect.ALLOW_STANDING, expires_seconds=3600)
    owner_scope = replace(scope, task_id=None)
    child_scope = PermissionScope("tenant-a", "user-a", "child-agent", "task-a")
    child = service.delegate(scope=owner_scope, parent_grant_id=parent.grant_id, child_scope=child_scope, effect=PermissionEffect.ALLOW_TASK, expires_seconds=300)
    assert child.parent_grant_id == parent.grant_id
    with pytest.raises(PermissionValidationError):
        service.delegate(scope=owner_scope, parent_grant_id=parent.grant_id, child_scope=PermissionScope("tenant-b", "user-a", "child-agent", "task-a"), effect=PermissionEffect.ALLOW_TASK, expires_seconds=300)
    with pytest.raises(PermissionValidationError):
        service.delegate(scope=owner_scope, parent_grant_id=parent.grant_id, child_scope=child_scope, effect=PermissionEffect.ALLOW_STANDING, expires_seconds=7200)


def test_bypass_inputs_fail_closed_or_preserve_exact_scope(tmp_path: Path) -> None:
    service, resolver, scope = _runtime(tmp_path)
    encoded = resolver.resolve(ToolCall("fetch", "web_fetch", {"url": "https%3A%2F%2Fexample.com%2Fdocs"}))
    plain = resolver.resolve(ToolCall("fetch", "web_fetch", {"url": "https://example.com/docs"}))
    assert encoded.resource == plain.resource
    request = service.evaluate(scope=scope, action=plain)
    service.decide_request(scope=scope, request_id=request.request_id or "", effect=PermissionEffect.ALLOW_STANDING, expires_seconds=300)
    assert service.evaluate(scope=scope, action=encoded).allowed is False
    mcp = resolver.resolve(ToolCall("mcp", "mcp__github__create_issue", {"title": "x"}))
    assert service.evaluate(scope=scope, action=mcp).allowed is False
    with pytest.raises(PermissionResolutionError):
        resolver.resolve(ToolCall("private", "web_fetch", {"url": "http://127.0.0.1/admin"}))
    with pytest.raises(PermissionResolutionError):
        resolver.resolve(ToolCall("private-v6", "web_fetch", {"url": "http://[::1]/admin"}))
    with pytest.raises(PermissionResolutionError):
        resolver.resolve(ToolCall("shell", "shell_command", {"command": "rm%20-rf%20workspace"}))
    with pytest.raises(PermissionResolutionError):
        resolver.resolve(ToolCall("unknown", "unregistered", {}))
    sensitive = resolver.resolve(ToolCall("sensitive", "sensitive_read", {}))
    assert service.evaluate(scope=scope, action=sensitive).allowed is False


def test_path_escape_and_symlink_alias_are_rejected(tmp_path: Path) -> None:
    _, resolver, _ = _runtime(tmp_path)
    outside = tmp_path.parent / "permission-outside"
    outside.mkdir(exist_ok=True)
    with pytest.raises(PermissionResolutionError, match="outside_workspace"):
        resolver.resolve(ToolCall("file", "file_read", {"path": "../permission-outside/secret.txt"}))
    link = tmp_path / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    else:
        with pytest.raises(PermissionResolutionError, match="outside_workspace"):
            resolver.resolve(ToolCall("file", "file_read", {"path": "escape/secret.txt"}))


def test_audit_never_stores_raw_arguments(tmp_path: Path) -> None:
    service, resolver, scope = _runtime(tmp_path)
    secret = "PRIVATE_PROMPT_DO_NOT_STORE"
    action = resolver.resolve(ToolCall("image", "image_generate", {"prompt": secret}))
    service.evaluate(scope=scope, action=action)
    assert secret.encode() not in (tmp_path / "permissions.sqlite3").read_bytes()
