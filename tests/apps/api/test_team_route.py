from __future__ import annotations

from fastapi import HTTPException
import pytest

from apps.api.main import app
from apps.api.routes.teams import create_teammate, inspect_worktree, send_message, team_state
from apps.api.schemas import CreateTeammateRequest, TeamMessageRequest
from klara.permissions import PermissionEffect, PermissionScope, PermissionService, SQLitePermissionRepository
from klara.tasks import DurableTaskService, SQLiteTaskRepository
from klara.teams import OneShotExecution, SQLiteTeamRepository, TeamScope, TeamService


def test_team_api_permission_then_real_state(tmp_path):
    permissions = PermissionService(SQLitePermissionRepository(tmp_path / "permissions.sqlite3"))
    service = TeamService(
        SQLiteTeamRepository(tmp_path / "teams.sqlite3"),
        DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3")),
        permissions,
        project_root=tmp_path,
        executor=lambda *_: OneShotExecution("summary"),
    )
    scope = TeamScope("tenant", "owner", "default-team")
    permission_scope = PermissionScope("tenant", "owner", "klara")
    assert "/api/teams" in {route.path for route in app.routes}
    with pytest.raises(HTTPException) as caught:
        create_teammate(CreateTeammateRequest(name="Reviewer", role="Check evidence"), service, scope, permission_scope)
    assert caught.value.status_code == 409
    request_id = caught.value.detail["decision"]["request_id"]
    permissions.decide_request(scope=permission_scope, request_id=request_id, effect=PermissionEffect.ALLOW_STANDING, expires_seconds=3600)
    created = create_teammate(CreateTeammateRequest(name="Reviewer", role="Check evidence"), service, scope, permission_scope)
    agent_id = created["agent"]["agent_id"]
    sent = send_message(TeamMessageRequest(recipient_id=agent_id, kind="question", body="Status?"), service, scope)
    assert sent["message"]["body"] == "Status?"
    state = team_state(service, scope)
    assert state["agents"][0]["name"] == "Reviewer"
    assert state["mailbox_counts"][agent_id] == 1


def test_team_worktree_inspection_route_is_owner_scoped_and_read_only(tmp_path):
    import subprocess

    project = tmp_path / "repo"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Klara Test"], cwd=project, check=True)
    (project / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=project, check=True, capture_output=True)
    permissions = PermissionService(SQLitePermissionRepository(tmp_path / "permissions.sqlite3"))
    service = TeamService(
        SQLiteTeamRepository(tmp_path / "teams.sqlite3"),
        DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3")),
        permissions,
        project_root=project,
    )
    scope = TeamScope("tenant", "owner", "default-team")
    permission_scope = PermissionScope("tenant", "owner", "klara")
    with pytest.raises(HTTPException) as teammate_request:
        create_teammate(CreateTeammateRequest(name="Coder", role="Isolated edits"), service, scope, permission_scope)
    permissions.decide_request(scope=permission_scope, request_id=teammate_request.value.detail["decision"]["request_id"], effect=PermissionEffect.ALLOW_STANDING, expires_seconds=3600)
    agent = create_teammate(CreateTeammateRequest(name="Coder", role="Isolated edits"), service, scope, permission_scope)["agent"]
    with pytest.raises(Exception):
        service.create_worktree(scope=scope, permission_scope=permission_scope, agent_id=agent["agent_id"], task_id="task-1", branch_name="codex/api-inspection")
    pending = next(item for item in permissions.repository.list_requests(permission_scope) if item.status.value == "pending")
    permissions.decide_request(scope=permission_scope, request_id=pending.request_id, effect=PermissionEffect.ALLOW_STANDING, expires_seconds=3600)
    lease = service.create_worktree(scope=scope, permission_scope=permission_scope, agent_id=agent["agent_id"], task_id="task-1", branch_name="codex/api-inspection")
    path = __import__("pathlib").Path(lease.path)
    (path / "new.txt").write_text("safe", encoding="utf-8")

    payload = inspect_worktree(lease.worktree_id, service, scope)

    assert payload["changed_file_count"] == 1
    assert payload["files"][0]["path"] == "new.txt"
    assert "safe" not in str(payload)
