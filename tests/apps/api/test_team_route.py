from __future__ import annotations

from fastapi import HTTPException
import pytest

from apps.api.main import app
from apps.api.routes.teams import create_teammate, send_message, team_state
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
