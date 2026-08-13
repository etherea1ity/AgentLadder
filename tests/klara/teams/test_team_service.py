from __future__ import annotations

from datetime import UTC, datetime, timedelta
import subprocess

import pytest

from klara.core.tools import ToolSideEffect
from klara.permissions import PermissionAction, PermissionEffect, PermissionRisk, PermissionScope, PermissionService, PermissionValidationError, SQLitePermissionRepository
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope, TaskState
from klara.teams import AgentStatus, MessageKind, OneShotExecution, OneShotRequest, SQLiteTeamRepository, TeamNotFoundError, TeamPermissionRequired, TeamScope, TeamService, TeamValidationError


def _services(tmp_path, *, executor=None, project_root=None):
    permission_service = PermissionService(SQLitePermissionRepository(tmp_path / "permissions.sqlite3"))
    tasks = DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3"))
    teams = TeamService(SQLiteTeamRepository(tmp_path / "teams.sqlite3"), tasks, permission_service, project_root=project_root or tmp_path, executor=executor)
    return teams, tasks, permission_service


def _scope():
    return TeamScope("tenant-a", "owner-a", "team-a")


def _permission_scope():
    return PermissionScope("tenant-a", "owner-a", "klara")


def _approve_last_request(service: PermissionService, *, effect=PermissionEffect.ALLOW_STANDING):
    state = service.list_state(scope=_permission_scope())
    request = next(item for item in state["requests"] if item["status"] == "pending")
    return service.decide_request(scope=_permission_scope(), request_id=request["request_id"], effect=effect, expires_seconds=3600)


def test_one_shot_is_permissioned_clean_context_and_summary_only(tmp_path):
    observed = {}

    def executor(request, agent_id, child_task_id):
        observed.update(request=request, agent_id=agent_id, child_task_id=child_task_id)
        return OneShotExecution("Verified concise result", {"turns": 1})

    teams, tasks, permissions = _services(tmp_path, executor=executor)
    request = OneShotRequest("Check evidence", "Read the explicit packet only.", ("web_fetch",))
    with pytest.raises(TeamPermissionRequired):
        teams.spawn_one_shot(scope=_scope(), permission_scope=_permission_scope(), request=request, asynchronous=False)
    _approve_last_request(permissions)
    agent = teams.spawn_one_shot(scope=_scope(), permission_scope=_permission_scope(), request=request, asynchronous=False)

    assert agent.status is AgentStatus.COMPLETED
    assert agent.summary == "Verified concise result"
    assert agent.summary_sha256 and len(agent.summary_sha256) == 64
    assert agent.context_sha256 and "Read the explicit packet" not in agent.to_public_dict().values()
    assert observed["request"].instructions == "Read the explicit packet only."
    assert tasks.get(scope=TaskScope("tenant-a", "owner-a", agent.agent_id), task_id=agent.child_task_id).state is TaskState.COMPLETED
    returned = teams.inbox(scope=_scope(), recipient_id="klara")
    assert [(item.kind, item.body) for item in returned] == [(MessageKind.RESULT, "Verified concise result")]


def test_capabilities_fail_closed_and_tenant_mailboxes_are_opaque(tmp_path):
    teams, _, permissions = _services(tmp_path)
    with pytest.raises(TeamPermissionRequired):
        teams.create_teammate(scope=_scope(), permission_scope=_permission_scope(), name="Researcher", role="Read sources", capability_names=("web_fetch",))
    _approve_last_request(permissions)
    teammate = teams.create_teammate(scope=_scope(), permission_scope=_permission_scope(), name="Researcher", role="Read sources", capability_names=("web_fetch",))
    teams.send_message(scope=_scope(), sender_id="klara", recipient_id=teammate.agent_id, kind=MessageKind.QUESTION, body="Status?")
    assert [item.body for item in teams.inbox(scope=_scope(), recipient_id=teammate.agent_id)] == ["Status?"]
    with pytest.raises(TeamNotFoundError):
        teams.inbox(scope=TeamScope("tenant-b", "owner-b", "team-a"), recipient_id=teammate.agent_id)
    with pytest.raises(TeamValidationError, match="team_capability_not_allowed"):
        teams.create_teammate(scope=_scope(), permission_scope=_permission_scope(), name="Unsafe", role="Control", capability_names=("shell",))


def test_mailbox_cursor_ack_and_stopped_member_rejection(tmp_path):
    teams, _, permissions = _services(tmp_path)
    with pytest.raises(TeamPermissionRequired):
        teams.create_teammate(scope=_scope(), permission_scope=_permission_scope(), name="Writer", role="Draft summaries")
    _approve_last_request(permissions)
    agent = teams.create_teammate(scope=_scope(), permission_scope=_permission_scope(), name="Writer", role="Draft summaries")
    first = teams.send_message(scope=_scope(), sender_id="klara", recipient_id=agent.agent_id, kind=MessageKind.TASK_ASSIGNMENT, body="First")
    second = teams.send_message(scope=_scope(), sender_id="klara", recipient_id=agent.agent_id, kind=MessageKind.PROGRESS, body="Second")
    assert [item.message_id for item in teams.inbox(scope=_scope(), recipient_id=agent.agent_id, after_sequence=1)] == [second.message_id]
    assert teams.acknowledge(scope=_scope(), recipient_id=agent.agent_id, message_id=first.message_id).acknowledged_at
    teams.stop_agent(scope=_scope(), agent_id=agent.agent_id)
    with pytest.raises(TeamValidationError, match="team_recipient_stopped"):
        teams.send_message(scope=_scope(), sender_id="klara", recipient_id=agent.agent_id, kind=MessageKind.QUESTION, body="After stop")


def test_persistent_teammate_claims_through_durable_task_lease(tmp_path):
    teams, tasks, permissions = _services(tmp_path)
    with pytest.raises(TeamPermissionRequired):
        teams.create_teammate(scope=_scope(), permission_scope=_permission_scope(), name="Worker", role="Take bounded tasks")
    _approve_last_request(permissions)
    agent = teams.create_teammate(scope=_scope(), permission_scope=_permission_scope(), name="Worker", role="Take bounded tasks")
    task = tasks.create(scope=TaskScope("tenant-a", "owner-a", agent.agent_id), title="Bounded job")
    claim = teams.claim_task(scope=_scope(), agent_id=agent.agent_id, task_id=task.task_id)
    assert claim.task.state is TaskState.RUNNING
    assert claim.lease_token
    assert teams.get_agent(scope=_scope(), agent_id=agent.agent_id).status is AgentStatus.RUNNING


def test_permission_bubbling_is_attenuated_to_child_agent_and_task(tmp_path):
    teams, _, permissions = _services(tmp_path, executor=lambda *_: OneShotExecution("done"))
    request = OneShotRequest("Bounded child", "Do one task")
    with pytest.raises(TeamPermissionRequired):
        teams.spawn_one_shot(scope=_scope(), permission_scope=_permission_scope(), request=request, asynchronous=True)
    _approve_last_request(permissions)
    agent = teams.spawn_one_shot(scope=_scope(), permission_scope=_permission_scope(), request=request, asynchronous=True)

    action = PermissionAction(
        tool_name="web_fetch", capability="network_read", side_effect=ToolSideEffect.READ,
        resource_type="url", resource="https://example.com", risk=PermissionRisk.MEDIUM,
        destructive=False, externally_consequential=True, arguments_sha256="a" * 64,
    )
    task_permission_scope = PermissionScope("tenant-a", "owner-a", "klara", task_id=agent.child_task_id)
    decision = permissions.evaluate(scope=task_permission_scope, action=action)
    parent = permissions.decide_request(
        scope=task_permission_scope, request_id=decision.request_id, effect=PermissionEffect.ALLOW_TASK,
        expires_seconds=1800,
    ) if decision.request_id else None
    assert parent is not None
    child = teams.delegate_authority(
        scope=_scope(), permission_scope=task_permission_scope, agent_id=agent.agent_id,
        parent_grant_id=parent.grant_id, effect=PermissionEffect.ALLOW_TASK, expires_seconds=600,
    )
    assert child.scope.agent_id == agent.agent_id
    assert child.scope.task_id == agent.child_task_id
    assert child.parent_grant_id == parent.grant_id
    with pytest.raises(PermissionValidationError, match="exceeds_parent"):
        teams.delegate_authority(
            scope=_scope(), permission_scope=task_permission_scope, agent_id=agent.agent_id,
            parent_grant_id=parent.grant_id, effect=PermissionEffect.ALLOW_STANDING, expires_seconds=600,
        )
    teams.shutdown()


def test_real_git_worktree_stays_under_project_root_and_requires_exact_permissions(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Klara Test"], cwd=project, check=True)
    (project / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=project, check=True, capture_output=True)
    teams, _, permissions = _services(tmp_path, project_root=project)
    with pytest.raises(TeamPermissionRequired):
        teams.create_teammate(scope=_scope(), permission_scope=_permission_scope(), name="Coder", role="Isolated edits")
    _approve_last_request(permissions)
    agent = teams.create_teammate(scope=_scope(), permission_scope=_permission_scope(), name="Coder", role="Isolated edits")
    with pytest.raises(TeamPermissionRequired):
        teams.create_worktree(scope=_scope(), permission_scope=_permission_scope(), agent_id=agent.agent_id, task_id="task-1", branch_name="codex/test-worktree")
    _approve_last_request(permissions)
    lease = teams.create_worktree(scope=_scope(), permission_scope=_permission_scope(), agent_id=agent.agent_id, task_id="task-1", branch_name="codex/test-worktree")
    assert lease.status.value == "ready"
    assert (project / ".klara" / "worktrees") in __import__("pathlib").Path(lease.path).parents
    with pytest.raises(TeamValidationError, match="codex_prefix"):
        teams.create_worktree(scope=_scope(), permission_scope=_permission_scope(), agent_id=agent.agent_id, task_id="task-2", branch_name="unsafe")
    with pytest.raises(TeamPermissionRequired):
        teams.remove_worktree(scope=_scope(), permission_scope=_permission_scope(), worktree_id=lease.worktree_id)
    _approve_last_request(permissions)
    removed = teams.remove_worktree(scope=_scope(), permission_scope=_permission_scope(), worktree_id=lease.worktree_id)
    assert removed.status.value == "removed"
