from __future__ import annotations

import json

from klara.app.runtime_tools import runtime_tools
from klara.core.tools import ToolCall
from klara.permissions import PermissionEffect, PermissionScope, PermissionService, SQLitePermissionRepository
from klara.scheduler import SQLiteScheduleRepository, SchedulerService
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope
from klara.teams import OneShotExecution, SQLiteTeamRepository, TeamScope, TeamService
from klara.tools.executor import ToolExecutor


def _services(tmp_path):
    task_service = DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3"))
    task_scope = TaskScope("tenant-a", "owner-a", "klara")
    permission_service = PermissionService(SQLitePermissionRepository(tmp_path / "permissions.sqlite3"))
    permission_scope = PermissionScope("tenant-a", "owner-a", "klara")
    team_scope = TeamScope("tenant-a", "owner-a", "team-a")
    team_service = TeamService(
        SQLiteTeamRepository(tmp_path / "teams.sqlite3"),
        task_service,
        permission_service,
        project_root=tmp_path,
        executor=lambda *_: OneShotExecution("verified summary"),
    )
    scheduler_service = SchedulerService(
        SQLiteScheduleRepository(tmp_path / "schedules.sqlite3"), task_service
    )
    tools = runtime_tools(
        task_service=task_service,
        task_scope=task_scope,
        scheduler_service=scheduler_service,
        scheduler_scope=task_scope,
        scheduler_session_id="session-a",
        team_service=team_service,
        team_scope=team_scope,
        team_permission_scope=permission_scope,
    )
    return (
        ToolExecutor(list(tools)),
        task_service,
        task_scope,
        scheduler_service,
        team_service,
        team_scope,
        permission_service,
        permission_scope,
    )


def _call(executor: ToolExecutor, name: str, arguments: dict):
    return executor.execute(ToolCall(f"call-{name}", name, arguments))


def _approve_latest(permission_service: PermissionService, scope: PermissionScope) -> None:
    request = next(
        item
        for item in permission_service.repository.list_requests(scope)
        if item.status.value == "pending"
    )
    permission_service.decide_request(
        scope=scope,
        request_id=request.request_id,
        effect=PermissionEffect.ALLOW_STANDING,
        expires_seconds=3600,
    )


def test_task_and_schedule_tools_mutate_real_shared_services(tmp_path) -> None:
    executor, task_service, task_scope, scheduler_service, *_ = _services(tmp_path)

    task_result = _call(
        executor,
        "task_create",
        {"title": "Ship the report", "description": "Verify and publish"},
    )
    task_id = json.loads(task_result.content)["task"]["task_id"]
    assert task_service.get(scope=task_scope, task_id=task_id).title == "Ship the report"
    assert json.loads(task_result.public_content or "{}")["task_id"] == task_id
    assert "Verify and publish" not in (task_result.public_content or "")

    task_list = _call(executor, "task_list", {})
    task_list_payload = json.loads(task_list.content)
    assert task_list_payload["tasks"][0]["title"] == "Ship the report"
    assert "description" not in task_list_payload["tasks"][0]
    task_list_with_descriptions = _call(
        executor, "task_list", {"include_descriptions": True}
    )
    assert (
        json.loads(task_list_with_descriptions.content)["tasks"][0]["description"]
        == "Verify and publish"
    )

    schedule_result = _call(
        executor,
        "schedule_create",
        {
            "title": "Morning review",
            "task_description": "Read the current report",
            "kind": "daily",
            "timezone": "Asia/Shanghai",
            "local_time": "09:00",
        },
    )
    schedule_id = json.loads(schedule_result.content)["schedule"]["schedule_id"]
    assert scheduler_service.get(scope=task_scope, schedule_id=schedule_id).session_id == "session-a"
    assert "Read the current report" not in (schedule_result.public_content or "")


def test_team_tools_request_exact_authority_then_execute(tmp_path) -> None:
    (
        executor,
        _,
        _,
        _,
        team_service,
        team_scope,
        permission_service,
        permission_scope,
    ) = _services(tmp_path)

    first = _call(
        executor,
        "subagent_spawn",
        {"title": "Review", "instructions": "Check one bounded artifact."},
    )
    assert not first.ok
    assert first.error == "permission_approval_required"
    _approve_latest(permission_service, permission_scope)

    second = _call(
        executor,
        "subagent_spawn",
        {"title": "Review", "instructions": "Check one bounded artifact."},
    )
    payload = json.loads(second.content)
    assert second.ok
    assert payload["agent"]["kind"] == "one_shot"
    assert payload["agent"]["agent_id"] in {
        item.agent_id for item in team_service.list_agents(scope=team_scope)
    }
    assert "Check one bounded artifact" not in (second.public_content or "")
    team_service.shutdown()


def test_runtime_tool_catalog_is_complete_and_unique(tmp_path) -> None:
    executor, *_ = _services(tmp_path)
    names = [item.name for item in executor.specs]

    assert len(names) == len(set(names))
    assert set(names) == {
        "task_list", "task_create", "task_control",
        "schedule_list", "schedule_create", "schedule_control",
        "team_list", "subagent_spawn", "teammate_create", "team_message", "team_stop",
        "worktree_create", "worktree_inspect", "worktree_remove",
    }


def test_worktree_inspection_public_trace_omits_changed_paths(tmp_path) -> None:
    executor, _, _, _, team_service, team_scope, *_ = _services(tmp_path)
    team_service.inspect_worktree = lambda **_: {
        "schema_version": "klara.team-worktree-inspection.v1",
        "worktree_id": "worktree-a",
        "status": "ready",
        "head_sha": "a" * 40,
        "ahead": 1,
        "behind": 0,
        "conflict_count": 0,
        "changed_file_count": 1,
        "files": [{"path": "private/customer-plan.md", "status": "modified", "code": " M"}],
    }

    result = _call(executor, "worktree_inspect", {"worktree_id": "worktree-a"})

    assert result.ok
    assert "private/customer-plan.md" in result.content
    assert "private/customer-plan.md" not in (result.public_content or "")
    assert json.loads(result.public_content or "{}")["paths_exposed"] is False
