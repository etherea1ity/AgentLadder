"""Bounded orchestration policy for one-shot agents, teams, and worktrees."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
from typing import Callable

from klara.core.tools import ToolSideEffect
from klara.permissions import PermissionAction, PermissionDecision, PermissionEffect, PermissionGrant, PermissionRisk, PermissionScope, PermissionService
from klara.tasks import DurableTaskService, TaskLeaseError, TaskNotFoundError, TaskScope, TaskState, TaskTransitionError
from klara.teams.models import (
    AgentKind,
    AgentStatus,
    MessageKind,
    OneShotExecution,
    OneShotRequest,
    TeamAgent,
    TeamMessage,
    TeamScope,
    WorktreeLease,
    WorktreeStatus,
    new_agent_id,
    new_team_message_id,
    new_worktree_id,
    utc_now_iso,
)
from klara.teams.repository import SQLiteTeamRepository


OneShotExecutor = Callable[[OneShotRequest, str, str], OneShotExecution]


class TeamNotFoundError(LookupError):
    pass


class TeamValidationError(ValueError):
    pass


class TeamPermissionRequired(PermissionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class TeamService:
    """Make delegation explicit, isolated, durable, permissioned, and bounded."""

    MAX_TEAMMATES = 8
    MAX_INSTRUCTION_CHARS = 12_000
    MAX_MESSAGE_CHARS = 8_000
    MAX_SUMMARY_CHARS = 12_000
    ROOT_AGENT_ID = "klara"
    ALLOWED_CAPABILITIES = frozenset(
        {
            "current_time",
            "web_fetch",
            "web_search",
            "evidence_submit",
            "skills_list",
            "skill_view",
            "memory_search",
            "update_activity",
        }
    )

    def __init__(
        self,
        repository: SQLiteTeamRepository,
        task_service: DurableTaskService,
        permission_service: PermissionService,
        *,
        project_root: str | Path,
        executor: OneShotExecutor | None = None,
    ) -> None:
        self.repository = repository
        self.task_service = task_service
        self.permission_service = permission_service
        self.project_root = Path(project_root).resolve()
        self.worktree_root = (self.project_root / ".klara" / "worktrees").resolve()
        self.executor = executor
        self._threads: dict[str, threading.Thread] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()

    def create_teammate(
        self,
        *,
        scope: TeamScope,
        permission_scope: PermissionScope,
        name: str,
        role: str,
        capability_names: tuple[str, ...] = (),
        parent_agent_id: str = ROOT_AGENT_ID,
    ) -> TeamAgent:
        capabilities = self._capabilities(capability_names)
        self._authorize(permission_scope, scope, "create_teammate", {"name": name, "role": role, "capability_names": list(capabilities)})
        persistent = [item for item in self.repository.list_agents(scope) if item.kind is AgentKind.TEAMMATE and item.status is not AgentStatus.STOPPED]
        if len(persistent) >= self.MAX_TEAMMATES:
            raise TeamValidationError("team_member_limit_reached")
        return self._create_agent(
            scope=scope,
            name=name,
            role=role,
            kind=AgentKind.TEAMMATE,
            status=AgentStatus.IDLE,
            capability_names=capabilities,
            parent_agent_id=parent_agent_id,
        )

    def spawn_one_shot(
        self,
        *,
        scope: TeamScope,
        permission_scope: PermissionScope,
        request: OneShotRequest,
        asynchronous: bool = True,
    ) -> TeamAgent:
        title = _clean(request.title, 160)
        instructions = request.instructions.strip()
        if not title or not instructions:
            raise TeamValidationError("subagent_title_and_instructions_required")
        if len(instructions) > self.MAX_INSTRUCTION_CHARS:
            raise TeamValidationError("subagent_instruction_too_large")
        capabilities = self._capabilities(request.capability_names)
        request = replace(request, title=title, instructions=instructions, capability_names=capabilities)
        self._authorize(
            permission_scope,
            scope,
            "spawn_one_shot",
            {"title": title, "capability_names": list(capabilities), "parent_task_id": request.parent_task_id},
        )
        agent_id = new_agent_id()
        child_scope = TaskScope(scope.tenant_id, scope.owner_id, agent_id)
        child_task = self.task_service.create(
            scope=child_scope,
            title=title,
            description="Delegated one-shot task packet.",
            parent_task_id=request.parent_task_id,
            max_attempts=1,
        )
        context_hash = _hash(json.dumps({"title": title, "instructions": instructions, "capabilities": capabilities}, ensure_ascii=False, sort_keys=True))
        agent = TeamAgent(
            agent_id=agent_id,
            scope=scope,
            name=title,
            role="one-shot specialist",
            kind=AgentKind.ONE_SHOT,
            status=AgentStatus.RUNNING,
            capability_names=capabilities,
            parent_agent_id=request.parent_agent_id,
            parent_task_id=request.parent_task_id,
            child_task_id=child_task.task_id,
            context_sha256=context_hash,
        )
        self.repository.save_agent(agent)
        self.send_message(
            scope=scope,
            sender_id=request.parent_agent_id,
            recipient_id=agent.agent_id,
            kind=MessageKind.TASK_ASSIGNMENT,
            body=instructions,
            task_id=child_task.task_id,
        )
        if asynchronous:
            thread = threading.Thread(target=self._execute_one_shot, args=(scope, agent.agent_id, request), daemon=True)
            with self._lock:
                self._threads[agent.agent_id] = thread
            thread.start()
        else:
            self._execute_one_shot(scope, agent.agent_id, request)
        return self.get_agent(scope=scope, agent_id=agent.agent_id)

    def get_agent(self, *, scope: TeamScope, agent_id: str) -> TeamAgent:
        agent = self.repository.get_agent(scope, agent_id)
        if agent is None:
            raise TeamNotFoundError("team_agent_not_found")
        return agent

    def list_agents(self, *, scope: TeamScope) -> list[TeamAgent]:
        return self.repository.list_agents(scope)

    def send_message(
        self,
        *,
        scope: TeamScope,
        sender_id: str,
        recipient_id: str,
        kind: MessageKind,
        body: str,
        task_id: str | None = None,
    ) -> TeamMessage:
        if sender_id != self.ROOT_AGENT_ID:
            self.get_agent(scope=scope, agent_id=sender_id)
        if recipient_id != self.ROOT_AGENT_ID:
            recipient = self.get_agent(scope=scope, agent_id=recipient_id)
            if recipient.status is AgentStatus.STOPPED:
                raise TeamValidationError("team_recipient_stopped")
        clean_body = body.strip()
        if not clean_body:
            raise TeamValidationError("team_message_body_required")
        if len(clean_body) > self.MAX_MESSAGE_CHARS:
            raise TeamValidationError("team_message_too_large")
        message = TeamMessage(
            message_id=new_team_message_id(),
            scope=scope,
            sender_id=sender_id,
            recipient_id=recipient_id,
            kind=kind,
            body=clean_body,
            task_id=task_id,
            sequence=self.repository.next_sequence(scope, recipient_id),
            created_at=utc_now_iso(),
        )
        self.repository.append_message(message)
        return message

    def inbox(self, *, scope: TeamScope, recipient_id: str, after_sequence: int = 0) -> list[TeamMessage]:
        if recipient_id != self.ROOT_AGENT_ID:
            self.get_agent(scope=scope, agent_id=recipient_id)
        if after_sequence < 0:
            raise TeamValidationError("team_inbox_cursor_invalid")
        return self.repository.list_inbox(scope, recipient_id, after_sequence=after_sequence)

    def acknowledge(self, *, scope: TeamScope, recipient_id: str, message_id: str) -> TeamMessage:
        message = self.repository.get_message(scope, recipient_id, message_id)
        if message is None:
            raise TeamNotFoundError("team_message_not_found")
        if message.acknowledged_at is None:
            message = replace(message, acknowledged_at=utc_now_iso())
            self.repository.save_message(message)
        return message

    def claim_task(self, *, scope: TeamScope, agent_id: str, task_id: str, lease_seconds: int = 60):
        agent = self.get_agent(scope=scope, agent_id=agent_id)
        if agent.kind is not AgentKind.TEAMMATE or agent.status not in {AgentStatus.IDLE, AgentStatus.WAITING}:
            raise TeamValidationError("team_agent_cannot_claim")
        task_scope = TaskScope(scope.tenant_id, scope.owner_id, agent_id)
        task = self.task_service.get(scope=task_scope, task_id=task_id)
        if task.scope.agent_id != agent_id:
            raise TeamValidationError("team_task_not_assigned_to_agent")
        claim = self.task_service.claim(
            scope=task_scope,
            task_id=task_id,
            worker_id=f"teammate:{agent_id}",
            lease_seconds=lease_seconds,
        )
        self.repository.save_agent(replace(agent, status=AgentStatus.RUNNING, child_task_id=task_id, updated_at=utc_now_iso()))
        return claim

    def claim_next_task(self, *, scope: TeamScope, agent_id: str, lease_seconds: int = 60):
        """Claim the first currently-ready owner task through the durable CAS lease."""

        agent = self.get_agent(scope=scope, agent_id=agent_id)
        if agent.kind is not AgentKind.TEAMMATE or agent.status not in {AgentStatus.IDLE, AgentStatus.WAITING}:
            raise TeamValidationError("team_agent_cannot_claim")
        task_scope = TaskScope(scope.tenant_id, scope.owner_id, agent_id)
        candidates = sorted(
            (item for item in self.task_service.list(scope=task_scope) if item.state is TaskState.READY),
            key=lambda item: (item.created_at, item.task_id),
        )
        for task in candidates:
            try:
                return self.claim_task(scope=scope, agent_id=agent_id, task_id=task.task_id, lease_seconds=lease_seconds)
            except (TaskLeaseError, TaskTransitionError):
                continue
        raise TeamValidationError("team_no_ready_task")

    def delegate_authority(
        self,
        *,
        scope: TeamScope,
        permission_scope: PermissionScope,
        agent_id: str,
        parent_grant_id: str,
        effect: PermissionEffect,
        expires_seconds: int,
    ) -> PermissionGrant:
        """Bubble only attenuated, same-action authority into one delegated task."""

        agent = self.get_agent(scope=scope, agent_id=agent_id)
        child_scope = PermissionScope(
            tenant_id=permission_scope.tenant_id,
            actor_id=permission_scope.actor_id,
            agent_id=agent.agent_id,
            task_id=agent.child_task_id,
        )
        return self.permission_service.delegate(
            scope=permission_scope,
            parent_grant_id=parent_grant_id,
            child_scope=child_scope,
            effect=effect,
            expires_seconds=expires_seconds,
        )

    def stop_agent(self, *, scope: TeamScope, agent_id: str) -> TeamAgent:
        agent = self.get_agent(scope=scope, agent_id=agent_id)
        with self._lock:
            self._cancelled.add(agent_id)
        if agent.child_task_id:
            try:
                task = self.task_service.get(scope=TaskScope(scope.tenant_id, scope.owner_id, agent_id), task_id=agent.child_task_id)
                if task.state not in {TaskState.COMPLETED, TaskState.CANCELLED}:
                    self.task_service.cancel(scope=TaskScope(scope.tenant_id, scope.owner_id, agent_id), task_id=task.task_id)
            except (TaskNotFoundError, TaskTransitionError):
                pass
        stopped = replace(agent, status=AgentStatus.STOPPED, updated_at=utc_now_iso())
        self.repository.save_agent(stopped)
        return stopped

    def create_worktree(
        self,
        *,
        scope: TeamScope,
        permission_scope: PermissionScope,
        agent_id: str,
        task_id: str,
        branch_name: str,
        base_ref: str = "HEAD",
    ) -> WorktreeLease:
        self.get_agent(scope=scope, agent_id=agent_id)
        branch = _git_ref(branch_name, prefix_required=True)
        base = _git_ref(base_ref, prefix_required=False)
        self._authorize(permission_scope, scope, "create_worktree", {"agent_id": agent_id, "task_id": task_id, "branch_name": branch, "base_ref": base}, destructive=False)
        identifier = new_worktree_id()
        path = (self.worktree_root / identifier).resolve()
        _require_contained(self.worktree_root, path)
        now = utc_now_iso()
        lease = WorktreeLease(identifier, scope, agent_id, task_id, branch, base, str(path), WorktreeStatus.CREATING, None, None, now, now)
        self.repository.save_worktree(lease)
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        try:
            self._git("worktree", "add", "-b", branch, str(path), base)
            head = self._git("-C", str(path), "rev-parse", "HEAD").strip()
            lease = replace(lease, status=WorktreeStatus.READY, head_sha=head, updated_at=utc_now_iso())
        except Exception as exc:
            lease = replace(lease, status=WorktreeStatus.FAILED, error_code=_public_git_error(exc), updated_at=utc_now_iso())
        self.repository.save_worktree(lease)
        return lease

    def remove_worktree(self, *, scope: TeamScope, permission_scope: PermissionScope, worktree_id: str) -> WorktreeLease:
        lease = self.repository.get_worktree(scope, worktree_id)
        if lease is None:
            raise TeamNotFoundError("team_worktree_not_found")
        path = Path(lease.path).resolve()
        _require_contained(self.worktree_root, path)
        self._authorize(permission_scope, scope, "remove_worktree", {"worktree_id": worktree_id, "path_sha256": _hash(str(path))}, destructive=True)
        removing = replace(lease, status=WorktreeStatus.REMOVING, updated_at=utc_now_iso())
        self.repository.save_worktree(removing)
        try:
            self._git("worktree", "remove", str(path))
            removed = replace(removing, status=WorktreeStatus.REMOVED, removed_at=utc_now_iso(), updated_at=utc_now_iso())
        except Exception as exc:
            removed = replace(removing, status=WorktreeStatus.FAILED, error_code=_public_git_error(exc), updated_at=utc_now_iso())
        self.repository.save_worktree(removed)
        return removed

    def list_state(self, *, scope: TeamScope) -> dict[str, object]:
        agents = self.repository.list_agents(scope)
        return {
            "schema_version": "klara.team-state.v1",
            "team": scope.to_public_dict(),
            "agents": [item.to_public_dict() for item in agents],
            "root_inbox": [item.to_public_dict() for item in self.repository.list_inbox(scope, self.ROOT_AGENT_ID)],
            "mailbox_counts": {item.agent_id: len(self.repository.list_inbox(scope, item.agent_id)) for item in agents},
            "worktrees": [item.to_public_dict() for item in self.repository.list_worktrees(scope)],
        }

    def inspect_worktree(self, *, scope: TeamScope, worktree_id: str) -> dict[str, object]:
        """Project a read-only Git status without exposing file contents."""

        lease = self.repository.get_worktree(scope, worktree_id)
        if lease is None:
            raise TeamNotFoundError("team_worktree_not_found")
        path = Path(lease.path).resolve()
        _require_contained(self.worktree_root, path)
        if lease.status is not WorktreeStatus.READY or not path.is_dir():
            return {
                "schema_version": "klara.team-worktree-inspection.v1",
                "worktree_id": lease.worktree_id,
                "status": lease.status.value,
                "head_sha": lease.head_sha,
                "ahead": 0,
                "behind": 0,
                "conflict_count": 0,
                "changed_file_count": 0,
                "files": [],
            }
        porcelain = self._git("-C", str(path), "status", "--porcelain=v1", "--untracked-files=all")
        rows: list[dict[str, str]] = []
        conflict_codes = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
        for raw in porcelain.splitlines()[:200]:
            if len(raw) < 4:
                continue
            code = raw[:2]
            rows.append(
                {
                    "path": raw[3:][:400],
                    "status": _git_status_label(code),
                    "code": code,
                }
            )
        ahead, behind = self._worktree_divergence(path, lease.base_ref)
        head = self._git("-C", str(path), "rev-parse", "HEAD").strip()
        return {
            "schema_version": "klara.team-worktree-inspection.v1",
            "worktree_id": lease.worktree_id,
            "status": lease.status.value,
            "head_sha": head,
            "ahead": ahead,
            "behind": behind,
            "conflict_count": sum(1 for row in rows if row["code"] in conflict_codes),
            "changed_file_count": len(rows),
            "files": rows,
        }

    def shutdown(self) -> None:
        with self._lock:
            self._cancelled.update(self._threads)
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=2)

    def _create_agent(self, *, scope: TeamScope, name: str, role: str, kind: AgentKind, status: AgentStatus, capability_names: tuple[str, ...], parent_agent_id: str) -> TeamAgent:
        agent = TeamAgent(
            agent_id=new_agent_id(), scope=scope, name=_clean(name, 80), role=_clean(role, 160), kind=kind,
            status=status, capability_names=self._capabilities(capability_names), parent_agent_id=parent_agent_id,
        )
        if not agent.name or not agent.role:
            raise TeamValidationError("team_agent_name_and_role_required")
        self.repository.save_agent(agent)
        return agent

    def _execute_one_shot(self, scope: TeamScope, agent_id: str, request: OneShotRequest) -> None:
        agent = self.get_agent(scope=scope, agent_id=agent_id)
        task_scope = TaskScope(scope.tenant_id, scope.owner_id, agent_id)
        if self.executor is None:
            self._fail_agent(agent, task_scope, "subagent_executor_unavailable")
            return
        claim = None
        try:
            claim = self.task_service.claim(scope=task_scope, task_id=str(agent.child_task_id), worker_id=f"one-shot:{agent_id}", lease_seconds=3600)
            self.task_service.progress(scope=task_scope, task_id=str(agent.child_task_id), lease_token=claim.lease_token, progress=10, current_step="Running isolated task packet")
            result = self.executor(request, agent_id, str(agent.child_task_id))
            with self._lock:
                cancelled = agent_id in self._cancelled
            current_task = self.task_service.get(scope=task_scope, task_id=str(agent.child_task_id))
            if cancelled or current_task.state is TaskState.CANCELLED:
                return
            summary = result.summary.strip()[: self.MAX_SUMMARY_CHARS]
            if not summary:
                raise TeamValidationError("subagent_empty_summary")
            self.task_service.progress(scope=task_scope, task_id=current_task.task_id, lease_token=claim.lease_token, progress=95, current_step="Returning summary-only result")
            self.task_service.complete(scope=task_scope, task_id=current_task.task_id, lease_token=claim.lease_token)
            finished = replace(agent, status=AgentStatus.COMPLETED, summary=summary, summary_sha256=_hash(summary), updated_at=utc_now_iso())
            self.repository.save_agent(finished)
            self.send_message(scope=scope, sender_id=agent_id, recipient_id=agent.parent_agent_id or self.ROOT_AGENT_ID, kind=MessageKind.RESULT, body=summary, task_id=agent.child_task_id)
        except Exception as exc:
            self._fail_agent(agent, task_scope, _public_error(exc), lease_token=claim.lease_token if claim else None)
        finally:
            with self._lock:
                self._threads.pop(agent_id, None)

    def _fail_agent(self, agent: TeamAgent, task_scope: TaskScope, code: str, *, lease_token: str | None = None) -> None:
        try:
            task = self.task_service.get(scope=task_scope, task_id=str(agent.child_task_id))
            if task.state is TaskState.RUNNING:
                if lease_token:
                    self.task_service.fail(scope=task_scope, task_id=task.task_id, lease_token=lease_token, code=code, message="Delegated execution failed within its bounded runtime.")
                else:
                    self.task_service.cancel(scope=task_scope, task_id=task.task_id)
        except Exception:
            pass
        failed = replace(agent, status=AgentStatus.FAILED, error_code=code[:160], updated_at=utc_now_iso())
        self.repository.save_agent(failed)

    def _capabilities(self, values: tuple[str, ...]) -> tuple[str, ...]:
        clean = tuple(dict.fromkeys(item.strip() for item in values if item.strip()))
        unknown = sorted(set(clean) - self.ALLOWED_CAPABILITIES)
        if unknown:
            raise TeamValidationError("team_capability_not_allowed:" + ",".join(unknown))
        return clean

    def _authorize(self, permission_scope: PermissionScope, scope: TeamScope, operation: str, arguments: dict[str, object], *, destructive: bool = False) -> None:
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        action = PermissionAction(
            tool_name="team_runtime",
            capability=operation,
            side_effect=ToolSideEffect.CONTROL if operation.endswith("worktree") else ToolSideEffect.WRITE,
            resource_type="team",
            resource=f"team:{scope.team_id}/{operation}",
            risk=PermissionRisk.CRITICAL if destructive else PermissionRisk.HIGH,
            destructive=destructive,
            externally_consequential=True,
            arguments_sha256=_hash(encoded),
        )
        decision = self.permission_service.evaluate(scope=permission_scope, action=action)
        if not decision.allowed:
            raise TeamPermissionRequired(decision)

    def _git(self, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=self.project_root, capture_output=True, text=True, timeout=60, check=False, shell=False)
        if result.returncode != 0:
            raise TeamValidationError("git_operation_failed:" + (result.stderr.strip() or result.stdout.strip())[:400])
        return result.stdout

    def _worktree_divergence(self, path: Path, base_ref: str) -> tuple[int, int]:
        try:
            value = self._git("-C", str(path), "rev-list", "--left-right", "--count", f"{base_ref}...HEAD")
            behind, ahead = (int(item) for item in value.strip().split())
            return ahead, behind
        except (TeamValidationError, ValueError):
            return 0, 0


def _clean(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_ref(value: str, *, prefix_required: bool) -> str:
    clean = value.strip()
    if not clean or clean.startswith("-") or len(clean) > 180 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", clean):
        raise TeamValidationError("team_git_ref_invalid")
    if ".." in clean or "//" in clean or clean.endswith(("/", ".", ".lock")) or "@{" in clean:
        raise TeamValidationError("team_git_ref_invalid")
    if prefix_required and not clean.startswith("codex/"):
        raise TeamValidationError("team_worktree_branch_requires_codex_prefix")
    return clean


def _require_contained(root: Path, path: Path) -> None:
    if path == root or root not in path.parents:
        raise TeamValidationError("team_worktree_path_outside_root")


def _public_git_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "already exists" in text or "already checked out" in text:
        return "worktree_branch_conflict"
    if "contains modified or untracked files" in text:
        return "worktree_has_uncommitted_changes"
    return "worktree_git_operation_failed"


def _git_status_label(code: str) -> str:
    if code == "??":
        return "untracked"
    if code in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
        return "conflict"
    if "D" in code:
        return "deleted"
    if "R" in code:
        return "renamed"
    if "A" in code:
        return "added"
    return "modified"


def _public_error(exc: Exception) -> str:
    if isinstance(exc, (TeamValidationError, TaskTransitionError, TaskLeaseError)):
        return str(exc)[:160]
    return f"subagent_internal_{type(exc).__name__}"[:160]
