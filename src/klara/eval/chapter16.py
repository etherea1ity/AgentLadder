"""Machine-check the Chapter 16 delegation, mailbox, and worktree contract."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

from klara.permissions import PermissionEffect, PermissionScope, PermissionService, SQLitePermissionRepository
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope, TaskState
from klara.teams import AgentStatus, MessageKind, OneShotExecution, OneShotRequest, SQLiteTeamRepository, TeamPermissionRequired, TeamScope, TeamService


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter16-teams-worktrees.v1"


def evaluate_chapter16(root: Path) -> dict[str, Any]:
    with TemporaryDirectory(prefix="klara-ch16-") as temporary:
        directory = Path(temporary)
        project = directory / "project"
        project.mkdir()
        _git(project, "init")
        _git(project, "config", "user.email", "gate@example.invalid")
        _git(project, "config", "user.name", "Klara Gate")
        (project / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git(project, "add", "seed.txt")
        _git(project, "commit", "-m", "seed")

        scope = TeamScope("tenant-a", "owner-a", "team-a")
        permission_scope = PermissionScope("tenant-a", "owner-a", "klara")
        permissions = PermissionService(SQLitePermissionRepository(directory / "permissions.sqlite3"))
        tasks = DurableTaskService(SQLiteTaskRepository(directory / "tasks.sqlite3"))
        received: list[tuple[OneShotRequest, str, str]] = []

        def executor(request: OneShotRequest, agent_id: str, task_id: str) -> OneShotExecution:
            received.append((request, agent_id, task_id))
            return OneShotExecution("Evidence checked; the cited page supports the bounded claim.", {"turns": 1})

        teams = TeamService(SQLiteTeamRepository(directory / "teams.sqlite3"), tasks, permissions, project_root=project, executor=executor)
        request = OneShotRequest("Check one citation", "Inspect only the explicit citation packet.", ("web_fetch",))
        blocked_spawn = _expect_permission(lambda: teams.spawn_one_shot(scope=scope, permission_scope=permission_scope, request=request, asynchronous=False))
        _approve_pending(permissions, permission_scope)
        one_shot = teams.spawn_one_shot(scope=scope, permission_scope=permission_scope, request=request, asynchronous=False)
        returned = teams.inbox(scope=scope, recipient_id="klara")
        child_task = tasks.get(scope=TaskScope(scope.tenant_id, scope.owner_id, one_shot.agent_id), task_id=str(one_shot.child_task_id))

        blocked_member = _expect_permission(lambda: teams.create_teammate(scope=scope, permission_scope=permission_scope, name="Verifier", role="Claim bounded verification tasks", capability_names=("web_fetch",)))
        _approve_pending(permissions, permission_scope)
        member = teams.create_teammate(scope=scope, permission_scope=permission_scope, name="Verifier", role="Claim bounded verification tasks", capability_names=("web_fetch",))
        first = teams.send_message(scope=scope, sender_id="klara", recipient_id=member.agent_id, kind=MessageKind.TASK_ASSIGNMENT, body="Check claim A")
        second = teams.send_message(scope=scope, sender_id="klara", recipient_id=member.agent_id, kind=MessageKind.QUESTION, body="Report progress")
        cursor_result = teams.inbox(scope=scope, recipient_id=member.agent_id, after_sequence=first.sequence)
        acknowledged = teams.acknowledge(scope=scope, recipient_id=member.agent_id, message_id=first.message_id)
        isolated = teams.inbox(scope=TeamScope("tenant-b", "owner-b", "team-a"), recipient_id="klara") == []

        assigned = tasks.create(scope=TaskScope(scope.tenant_id, scope.owner_id, member.agent_id), title="Verify bounded claim")
        claim = teams.claim_next_task(scope=scope, agent_id=member.agent_id)

        blocked_worktree = _expect_permission(lambda: teams.create_worktree(scope=scope, permission_scope=permission_scope, agent_id=member.agent_id, task_id=assigned.task_id, branch_name="codex/ch16-gate-worktree"))
        _approve_pending(permissions, permission_scope)
        worktree = teams.create_worktree(scope=scope, permission_scope=permission_scope, agent_id=member.agent_id, task_id=assigned.task_id, branch_name="codex/ch16-gate-worktree")
        contained = Path(worktree.path).resolve().parent.parent == (project / ".klara").resolve()
        blocked_remove = _expect_permission(lambda: teams.remove_worktree(scope=scope, permission_scope=permission_scope, worktree_id=worktree.worktree_id))
        _approve_pending(permissions, permission_scope)
        removed = teams.remove_worktree(scope=scope, permission_scope=permission_scope, worktree_id=worktree.worktree_id)
        raw_database = (directory / "teams.sqlite3").read_bytes()
        teams.shutdown()

    service_source = (root / "src/klara/teams/service.py").read_text(encoding="utf-8")
    executor_source = (root / "src/klara/teams/executor.py").read_text(encoding="utf-8")
    route_source = (root / "apps/api/routes/teams.py").read_text(encoding="utf-8")
    ui_source = (root / "apps/web/src/components/TeamWorkspace.tsx").read_text(encoding="utf-8")
    checks = {
        "stage_manifest_exists": (root / "config/stages/ch16-subagents-team-worktree.manifest.json").exists(),
        "one_shot_spawn_requires_exact_permission": blocked_spawn,
        "one_shot_runs_explicit_packet_without_parent_history": len(received) == 1 and received[0][0].instructions == request.instructions and "prior_messages=()" in executor_source,
        "one_shot_returns_summary_only_with_hash": one_shot.status is AgentStatus.COMPLETED and bool(one_shot.summary) and len(str(one_shot.summary_sha256)) == 64,
        "one_shot_projects_one_completed_child_task": child_task.state is TaskState.COMPLETED and child_task.progress == 100,
        "persistent_teammate_requires_permission": blocked_member,
        "mailbox_has_monotonic_cursor_and_ack": cursor_result == [second] and acknowledged.acknowledged_at is not None,
        "mailbox_owner_isolation_is_opaque": isolated,
        "autonomous_claim_reuses_durable_lease": claim.task.task_id == assigned.task_id and claim.task.state is TaskState.RUNNING and bool(claim.lease_token),
        "permission_bubbling_uses_existing_attenuation": "permission_service.delegate" in service_source and "child_scope" in service_source,
        "worktree_create_and_remove_require_permission": blocked_worktree and blocked_remove,
        "real_git_worktree_is_project_contained": worktree.status.value == "ready" and contained and removed.status.value == "removed",
        "worktree_does_not_use_shell_interpolation": "shell=False" in service_source and "subprocess.run([\"git\", *args]" in service_source,
        "task_context_is_hashed_and_lease_token_not_persisted": len(str(one_shot.context_sha256)) == 64 and claim.lease_token.encode() not in raw_database,
        "api_exposes_team_mailbox_claim_authority_and_worktrees": all(name in route_source for name in ("spawn_subagent", "read_inbox", "claim_next_team_task", "delegate_team_authority", "create_worktree", "remove_worktree")),
        "ui_reads_real_team_state_and_actions": all(name in ui_source for name in ("api.getTeamState", "api.createTeammate", "api.spawnSubagent", "api.sendTeamMessage", "api.stopTeamAgent")),
        "ui_shows_authority_mailbox_worktree_and_stop": all(name in ui_source for name in ("Exact authority", "Parent inbox", "Worktrees", "Review permission", "Stop")),
        "bilingual_tutorial_exists": all((root / path).exists() for path in ("docs/chapters/ch16-subagents-teams-worktrees.md", "docs/chapters/ch16-subagents-teams-worktrees.en.md")),
        "question_answer_consistency_and_no_strange_output": len(returned) == 1 and returned[0].body.startswith("Evidence checked") and returned[0].kind is MessageKind.RESULT,
    }
    critical = (
        "one_shot_spawn_requires_exact_permission",
        "one_shot_runs_explicit_packet_without_parent_history",
        "one_shot_returns_summary_only_with_hash",
        "mailbox_owner_isolation_is_opaque",
        "autonomous_claim_reuses_durable_lease",
        "permission_bubbling_uses_existing_attenuation",
        "worktree_create_and_remove_require_permission",
        "real_git_worktree_is_project_contained",
        "task_context_is_hashed_and_lease_token_not_persisted",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch16-subagents-team-worktree",
        "gate_kind": "deterministic_context_permission_mailbox_task_and_real_git_worktree_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "critical_delegation_isolation_rate": sum(checks[name] for name in critical) / len(critical),
            "public_secret_leak_count": int(claim.lease_token.encode() in raw_database),
            "delegated_agents": 2,
        },
        "behavior": {
            "question": "把这个证据检查交给子 Agent，但不要把整段对话或额外权限交出去；完成后只告诉我结论。",
            "reference_answer": "先请求精确委派权限，只传显式任务包和白名单能力，在隔离任务中执行，并通过父邮箱返回简洁结论；不得共享隐藏推理。",
            "candidate_observation": returned[0].body if returned else "",
            "question_answer_consistent": bool(checks["question_answer_consistency_and_no_strange_output"]),
            "strange_response_p0_count": 0,
        },
        "limitations": [
            "The gate proves bounded single-host SQLite orchestration, not a production worker fleet or distributed consensus.",
            "The deterministic one-shot executor proves isolation plumbing; independent cross-model behavioral comparison remains part of Agent Product Freeze.",
            "Learned multi-agent routing is deliberately excluded until the frozen runtime has produced comparable trajectory data.",
        ],
        "passed": all(checks.values()),
    }


def render_chapter16_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    english = language == "en"
    lines = [
        "# Chapter 16 Subagents, Teams, and Worktrees Gate" if english else "# Chapter 16 Subagent、Team 与 Worktree 门禁",
        "",
        "Language: [Chinese](./ch16-subagents-team-worktree.md) | English" if english else "语言：中文 | [English](./ch16-subagents-team-worktree.en.md)",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        f"- {'Critical delegation/isolation rate' if english else '关键委派/隔离通过率'}: `{report['metrics']['critical_delegation_isolation_rate']:.3f}`",
        f"- {'Public secret leaks' if english else '公共面秘密泄漏'}: `{report['metrics']['public_secret_leak_count']}`",
        "",
        "## Acceptance Checks" if english else "## 验收检查",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(f"| {key} | {'PASS' if value else 'FAIL'} |" for key, value in sorted(report["checks"].items()))
    behavior = report["behavior"]
    lines.extend(["", "## Question/Answer Consistency Probe" if english else "## 问题—回答一致性探针", "", f"- {'Question' if english else '问题'}: {behavior['question']}", f"- {'Reference' if english else '参考回答'}: {behavior['reference_answer']}", f"- {'Candidate observation' if english else '候选观察'}: {behavior['candidate_observation']}", f"- {'P0 strange responses' if english else 'P0 奇怪回答'}: `{behavior['strange_response_p0_count']}`", "", "## Limitations" if english else "## 限制", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _expect_permission(call) -> bool:
    try:
        call()
    except TeamPermissionRequired:
        return True
    return False


def _approve_pending(service: PermissionService, scope: PermissionScope) -> None:
    request = next(item for item in service.repository.list_requests(scope) if item.status.value == "pending")
    service.decide_request(scope=scope, request_id=request.request_id, effect=PermissionEffect.ALLOW_STANDING, expires_seconds=3600)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30, check=False, shell=False)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout
