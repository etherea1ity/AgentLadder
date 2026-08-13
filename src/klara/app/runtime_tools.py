"""Model-callable adapters for AgentLadder's durable product services."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSideEffect, ToolSpec
from klara.scheduler import MisfirePolicy, OverlapPolicy, ScheduleKind
from klara.teams import MessageKind, OneShotRequest
from klara.tools.base import BaseTool, ToolInputError


def runtime_tools(
    *,
    task_service: Any | None = None,
    task_scope: Any | None = None,
    scheduler_service: Any | None = None,
    scheduler_scope: Any | None = None,
    scheduler_session_id: str | None = None,
    team_service: Any | None = None,
    team_scope: Any | None = None,
    team_permission_scope: Any | None = None,
) -> tuple[BaseTool, ...]:
    """Return only adapters whose backing product service is configured."""

    tools: list[BaseTool] = []
    if task_service is not None and task_scope is not None:
        tools.extend(
            (
                TaskListTool(task_service, task_scope),
                TaskCreateTool(task_service, task_scope),
                TaskControlTool(task_service, task_scope),
            )
        )
    if (
        scheduler_service is not None
        and scheduler_scope is not None
        and scheduler_session_id is not None
    ):
        tools.extend(
            (
                ScheduleListTool(scheduler_service, scheduler_scope),
                ScheduleCreateTool(
                    scheduler_service, scheduler_scope, scheduler_session_id
                ),
                ScheduleControlTool(scheduler_service, scheduler_scope),
            )
        )
    if (
        team_service is not None
        and team_scope is not None
        and team_permission_scope is not None
    ):
        tools.extend(
            (
                TeamListTool(team_service, team_scope),
                SubagentSpawnTool(team_service, team_scope, team_permission_scope),
                TeammateCreateTool(team_service, team_scope, team_permission_scope),
                TeamMessageTool(team_service, team_scope),
                TeamStopTool(team_service, team_scope),
                WorktreeCreateTool(team_service, team_scope, team_permission_scope),
                WorktreeInspectTool(team_service, team_scope),
                WorktreeRemoveTool(team_service, team_scope, team_permission_scope),
            )
        )
    return tuple(tools)


@dataclass(frozen=True)
class TaskListTool(BaseTool):
    service: Any
    scope: Any
    spec: ToolSpec = ToolSpec(
        name="task_list",
        description=(
            "List the current owner's durable tasks. Report only the fields the user "
            "asked for, normally title and lifecycle state; keep the final answer concise "
            "and do not offer an unrequested state change."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "include_descriptions": {
                    "type": "boolean",
                    "description": "Include private task descriptions only when the user explicitly asks for them.",
                    "default": False,
                }
            },
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="List durable tasks", category="tasks", side_effect=ToolSideEffect.READ
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        include_descriptions = arguments.get("include_descriptions") is True
        tasks = []
        for item in self.service.list(scope=self.scope):
            task = {
                "task_id": item.task_id,
                "title": item.title,
                "state": item.state.value,
                "progress": item.progress,
                "current_step": item.current_step,
                "block_reason": item.block_reason,
            }
            if include_descriptions:
                task["description"] = item.description
            tasks.append(task)
        return _result(
            self,
            arguments,
            {"schema_version": "klara.agent-task-list.v1", "tasks": tasks},
            {
                "schema_version": "klara.agent-task-list-public.v1",
                "count": len(tasks),
                "states": [item["state"] for item in tasks],
                "private_descriptions_exposed": False,
            },
        )


@dataclass(frozen=True)
class TaskCreateTool(BaseTool):
    service: Any
    scope: Any
    spec: ToolSpec = ToolSpec(
        name="task_create",
        description=(
            "Create a durable task for work that must survive restart or be resumed later. "
            "Use todo_write instead for a lightweight current-chat plan."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 160},
                "description": {"type": "string", "maxLength": 2000},
                "dependency_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 24},
                "required_artifacts": {"type": "array", "items": {"type": "string"}, "maxItems": 24},
                "required_evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 24},
                "max_attempts": {"type": "integer", "minimum": 1, "maximum": 8},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Create durable task",
        category="tasks",
        side_effect=ToolSideEffect.WRITE,
        requires_approval=True,
        parallel_safe=False,
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            task = self.service.create(
                scope=self.scope,
                title=_required(arguments, "title"),
                description=_optional(arguments, "description"),
                dependency_ids=_strings(arguments, "dependency_ids"),
                required_artifacts=_strings(arguments, "required_artifacts"),
                required_evidence=_strings(arguments, "required_evidence"),
                max_attempts=_integer(arguments, "max_attempts", default=3),
            )
        except (ValueError, LookupError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(
            self,
            arguments,
            {
                "schema_version": "klara.agent-task.v1",
                "task": {
                    "task_id": task.task_id,
                    "title": task.title,
                    "state": task.state.value,
                },
            },
            {"schema_version": "klara.agent-task-public.v1", "task_id": task.task_id, "state": task.state.value},
        )


@dataclass(frozen=True)
class TaskControlTool(BaseTool):
    service: Any
    scope: Any
    spec: ToolSpec = ToolSpec(
        name="task_control",
        description="Cancel, resume, or explicitly retry one owned durable task.",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "action": {"type": "string", "enum": ["cancel", "resume", "retry"]},
            },
            "required": ["task_id", "action"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Control durable task",
        category="tasks",
        side_effect=ToolSideEffect.CONTROL,
        requires_approval=True,
        parallel_safe=False,
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            task_id = _required(arguments, "task_id")
            action = _required(arguments, "action")
            operation = {"cancel": self.service.cancel, "resume": self.service.resume, "retry": self.service.retry}.get(action)
            if operation is None:
                raise ToolInputError("task_action_not_supported")
            task = operation(scope=self.scope, task_id=task_id)
        except (ValueError, LookupError, PermissionError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(
            self,
            arguments,
            {
                "schema_version": "klara.agent-task.v1",
                "task": {
                    "task_id": task.task_id,
                    "title": task.title,
                    "state": task.state.value,
                },
            },
            {"schema_version": "klara.agent-task-public.v1", "task_id": task.task_id, "state": task.state.value},
        )


@dataclass(frozen=True)
class ScheduleListTool(BaseTool):
    service: Any
    scope: Any
    spec: ToolSpec = ToolSpec(
        name="schedule_list",
        description="List the current owner's schedules and occurrence states.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    )
    metadata: ToolMetadata = ToolMetadata(
        label="List schedules", category="scheduler", side_effect=ToolSideEffect.READ
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        state = self.service.state(scope=self.scope)
        schedules = state.get("schedules", [])
        model_schedules = [
            {
                key: item.get(key)
                for key in (
                    "schedule_id",
                    "title",
                    "kind",
                    "timezone",
                    "status",
                    "next_run_at",
                    "last_scheduled_at",
                    "last_result",
                )
            }
            for item in schedules
        ]
        return _result(
            self,
            arguments,
            {
                "schema_version": "klara.agent-schedule-list.v1",
                "schedules": model_schedules,
            },
            {
                "schema_version": "klara.agent-schedule-list-public.v1",
                "count": len(schedules),
                "statuses": [item.get("status") for item in schedules],
                "private_descriptions_exposed": False,
            },
        )


@dataclass(frozen=True)
class ScheduleCreateTool(BaseTool):
    service: Any
    scope: Any
    session_id: str
    spec: ToolSpec = ToolSpec(
        name="schedule_create",
        description=(
            "Create a durable one-time, interval, daily, or weekly schedule bound to the current chat. "
            "Use an explicit IANA timezone."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 160},
                "task_description": {"type": "string", "maxLength": 4000},
                "kind": {"type": "string", "enum": [item.value for item in ScheduleKind]},
                "timezone": {"type": "string"},
                "run_at": {"type": "string"},
                "local_time": {"type": "string"},
                "weekdays": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6}, "maxItems": 7},
                "interval_seconds": {"type": "integer", "minimum": 60},
            },
            "required": ["title", "task_description", "kind", "timezone"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Create schedule",
        category="scheduler",
        side_effect=ToolSideEffect.CONTROL,
        requires_approval=True,
        parallel_safe=False,
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            schedule = self.service.create(
                scope=self.scope,
                title=_required(arguments, "title"),
                task_description=_required(arguments, "task_description"),
                session_id=self.session_id,
                kind=ScheduleKind(_required(arguments, "kind")),
                timezone=_required(arguments, "timezone"),
                run_at=_optional(arguments, "run_at") or None,
                local_time=_optional(arguments, "local_time") or None,
                weekdays=tuple(_integers(arguments, "weekdays")),
                interval_seconds=_optional_integer(arguments, "interval_seconds"),
                misfire_policy=MisfirePolicy.FIRE_ONCE,
                overlap_policy=OverlapPolicy.SKIP,
            )
        except (ValueError, LookupError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(
            self,
            arguments,
            {
                "schema_version": "klara.agent-schedule.v1",
                "schedule": _schedule_summary(schedule),
            },
            {"schema_version": "klara.agent-schedule-public.v1", "schedule_id": schedule.schedule_id, "status": schedule.status.value, "next_run_at": schedule.next_run_at},
        )


@dataclass(frozen=True)
class ScheduleControlTool(BaseTool):
    service: Any
    scope: Any
    spec: ToolSpec = ToolSpec(
        name="schedule_control",
        description="Pause, resume, cancel, or run now one owned schedule.",
        input_schema={
            "type": "object",
            "properties": {
                "schedule_id": {"type": "string"},
                "action": {"type": "string", "enum": ["pause", "resume", "cancel", "run_now"]},
            },
            "required": ["schedule_id", "action"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Control schedule",
        category="scheduler",
        side_effect=ToolSideEffect.CONTROL,
        requires_approval=True,
        parallel_safe=False,
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            schedule_id = _required(arguments, "schedule_id")
            action = _required(arguments, "action")
            if action == "run_now":
                occurrence = self.service.run_now(scope=self.scope, schedule_id=schedule_id)
                return _result(
                    self,
                    arguments,
                    {"schema_version": "klara.agent-schedule-occurrence.v1", "occurrence": occurrence.to_public_dict()},
                    {"schema_version": "klara.agent-schedule-occurrence-public.v1", "occurrence_id": occurrence.occurrence_id, "status": occurrence.status.value},
                )
            operation = {"pause": self.service.pause, "resume": self.service.resume, "cancel": self.service.cancel}.get(action)
            if operation is None:
                raise ToolInputError("schedule_action_not_supported")
            schedule = operation(scope=self.scope, schedule_id=schedule_id)
        except (ValueError, LookupError, PermissionError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(
            self,
            arguments,
            {
                "schema_version": "klara.agent-schedule.v1",
                "schedule": _schedule_summary(schedule),
            },
            {"schema_version": "klara.agent-schedule-public.v1", "schedule_id": schedule.schedule_id, "status": schedule.status.value},
        )


@dataclass(frozen=True)
class TeamListTool(BaseTool):
    service: Any
    scope: Any
    spec: ToolSpec = ToolSpec(
        name="team_list",
        description="List the current team's agents, mailbox counts, and worktree leases.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    )
    metadata: ToolMetadata = ToolMetadata(
        label="List team state", category="team", side_effect=ToolSideEffect.READ
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        state = self.service.list_state(scope=self.scope)
        model_state = {
            "schema_version": "klara.agent-team-list.v1",
            "agents": [
                {
                    key: item.get(key)
                    for key in (
                        "agent_id",
                        "name",
                        "role",
                        "kind",
                        "status",
                        "parent_agent_id",
                        "parent_task_id",
                        "child_task_id",
                    )
                }
                for item in state.get("agents", [])
            ],
            "mailbox_counts": state.get("mailbox_counts", {}),
            "worktrees": [
                {
                    key: item.get(key)
                    for key in (
                        "worktree_id",
                        "agent_id",
                        "task_id",
                        "branch_name",
                        "base_ref",
                        "status",
                        "head_sha",
                        "error_code",
                    )
                }
                for item in state.get("worktrees", [])
            ],
        }
        public = {
            "schema_version": "klara.agent-team-list-public.v1",
            "agent_count": len(state.get("agents", [])),
            "worktree_count": len(state.get("worktrees", [])),
            "mailbox_counts": state.get("mailbox_counts", {}),
            "instructions_or_paths_exposed": False,
        }
        return _result(self, arguments, model_state, public)


@dataclass(frozen=True)
class SubagentSpawnTool(BaseTool):
    service: Any
    scope: Any
    permission_scope: Any
    spec: ToolSpec = ToolSpec(
        name="subagent_spawn",
        description=(
            "Spawn one bounded clean-context subagent for an independent task packet. "
            "The child returns a summary only and cannot inherit undeclared capabilities."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 160},
                "instructions": {"type": "string", "minLength": 1, "maxLength": 12000},
                "capability_names": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
                "parent_task_id": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["title", "instructions"],
            "additionalProperties": False,
        },
    )
    # TeamService performs the authoritative permission check. The outer hook is
    # deliberately read-classified to avoid asking for two different grants.
    metadata: ToolMetadata = ToolMetadata(
        label="Spawn subagent", category="team", side_effect=ToolSideEffect.READ, parallel_safe=False
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            agent = self.service.spawn_one_shot(
                scope=self.scope,
                permission_scope=self.permission_scope,
                request=OneShotRequest(
                    title=_required(arguments, "title"),
                    instructions=_required(arguments, "instructions"),
                    capability_names=_strings(arguments, "capability_names"),
                    parent_task_id=_optional(arguments, "parent_task_id") or None,
                    model=_optional(arguments, "model") or None,
                ),
                asynchronous=True,
            )
        except (ValueError, LookupError, PermissionError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(
            self,
            arguments,
            {"schema_version": "klara.agent-subagent.v1", "agent": _agent_summary(agent)},
            {"schema_version": "klara.agent-subagent-public.v1", "agent_id": agent.agent_id, "child_task_id": agent.child_task_id, "status": agent.status.value, "instructions_exposed": False},
        )


@dataclass(frozen=True)
class TeammateCreateTool(BaseTool):
    service: Any
    scope: Any
    permission_scope: Any
    spec: ToolSpec = ToolSpec(
        name="teammate_create",
        description="Create one persistent teammate with an explicitly bounded role and capability set.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "role": {"type": "string", "minLength": 1, "maxLength": 160},
                "capability_names": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
            },
            "required": ["name", "role"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Create teammate", category="team", side_effect=ToolSideEffect.READ, parallel_safe=False
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            agent = self.service.create_teammate(
                scope=self.scope,
                permission_scope=self.permission_scope,
                name=_required(arguments, "name"),
                role=_required(arguments, "role"),
                capability_names=_strings(arguments, "capability_names"),
            )
        except (ValueError, LookupError, PermissionError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(
            self,
            arguments,
            {"schema_version": "klara.agent-teammate.v1", "agent": _agent_summary(agent)},
            {"schema_version": "klara.agent-teammate-public.v1", "agent_id": agent.agent_id, "status": agent.status.value},
        )


@dataclass(frozen=True)
class TeamMessageTool(BaseTool):
    service: Any
    scope: Any
    spec: ToolSpec = ToolSpec(
        name="team_message",
        description="Send a bounded message to a known teammate or the root agent.",
        input_schema={
            "type": "object",
            "properties": {
                "recipient_id": {"type": "string"},
                "kind": {"type": "string", "enum": [item.value for item in MessageKind]},
                "body": {"type": "string", "minLength": 1, "maxLength": 8000},
                "task_id": {"type": "string"},
            },
            "required": ["recipient_id", "kind", "body"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Message teammate",
        category="team",
        side_effect=ToolSideEffect.WRITE,
        requires_approval=True,
        parallel_safe=False,
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            message = self.service.send_message(
                scope=self.scope,
                sender_id="klara",
                recipient_id=_required(arguments, "recipient_id"),
                kind=MessageKind(_required(arguments, "kind")),
                body=_required(arguments, "body"),
                task_id=_optional(arguments, "task_id") or None,
            )
        except (ValueError, LookupError, PermissionError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(
            self,
            arguments,
            {
                "schema_version": "klara.agent-team-message.v1",
                "message": {
                    "message_id": message.message_id,
                    "recipient_id": message.recipient_id,
                    "kind": message.kind.value,
                    "task_id": message.task_id,
                },
            },
            {"schema_version": "klara.agent-team-message-public.v1", "message_id": message.message_id, "recipient_id": message.recipient_id, "body_exposed": False},
        )


@dataclass(frozen=True)
class TeamStopTool(BaseTool):
    service: Any
    scope: Any
    spec: ToolSpec = ToolSpec(
        name="team_stop",
        description="Stop one owned teammate or subagent.",
        input_schema={
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Stop team agent",
        category="team",
        side_effect=ToolSideEffect.CONTROL,
        requires_approval=True,
        parallel_safe=False,
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            agent = self.service.stop_agent(scope=self.scope, agent_id=_required(arguments, "agent_id"))
        except (ValueError, LookupError, PermissionError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(self, arguments, {"agent": _agent_summary(agent)}, {"agent_id": agent.agent_id, "status": agent.status.value})


@dataclass(frozen=True)
class WorktreeCreateTool(BaseTool):
    service: Any
    scope: Any
    permission_scope: Any
    spec: ToolSpec = ToolSpec(
        name="worktree_create",
        description="Create a contained Git worktree on a new codex/ branch for one teammate task.",
        input_schema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "task_id": {"type": "string"},
                "branch_name": {"type": "string", "pattern": "^codex/"},
                "base_ref": {"type": "string"},
            },
            "required": ["agent_id", "task_id", "branch_name"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Create worktree", category="team", side_effect=ToolSideEffect.READ, parallel_safe=False
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            lease = self.service.create_worktree(
                scope=self.scope,
                permission_scope=self.permission_scope,
                agent_id=_required(arguments, "agent_id"),
                task_id=_required(arguments, "task_id"),
                branch_name=_required(arguments, "branch_name"),
                base_ref=_optional(arguments, "base_ref") or "HEAD",
            )
        except (ValueError, LookupError, PermissionError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(
            self,
            arguments,
            {"schema_version": "klara.agent-worktree.v1", "worktree": _worktree_summary(lease)},
            {"schema_version": "klara.agent-worktree-public.v1", "worktree_id": lease.worktree_id, "branch_name": lease.branch_name, "status": lease.status.value, "path_exposed": False},
        )


@dataclass(frozen=True)
class WorktreeInspectTool(BaseTool):
    service: Any
    scope: Any
    spec: ToolSpec = ToolSpec(
        name="worktree_inspect",
        description="Read the contained Git status and divergence of one owned worktree without file contents.",
        input_schema={
            "type": "object",
            "properties": {"worktree_id": {"type": "string"}},
            "required": ["worktree_id"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Inspect worktree", category="team", side_effect=ToolSideEffect.READ
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            inspection = self.service.inspect_worktree(scope=self.scope, worktree_id=_required(arguments, "worktree_id"))
        except (ValueError, LookupError, PermissionError) as exc:
            return self.failure(arguments, _error(exc))
        public = {
            "schema_version": "klara.agent-worktree-inspection-public.v1",
            "worktree_id": inspection.get("worktree_id"),
            "status": inspection.get("status"),
            "head_sha": inspection.get("head_sha"),
            "ahead": inspection.get("ahead", 0),
            "behind": inspection.get("behind", 0),
            "conflict_count": inspection.get("conflict_count", 0),
            "changed_file_count": inspection.get("changed_file_count", 0),
            "paths_exposed": False,
        }
        return _result(self, arguments, inspection, public)


@dataclass(frozen=True)
class WorktreeRemoveTool(BaseTool):
    service: Any
    scope: Any
    permission_scope: Any
    spec: ToolSpec = ToolSpec(
        name="worktree_remove",
        description="Remove one contained owned worktree. This is destructive and requires exact approval.",
        input_schema={
            "type": "object",
            "properties": {"worktree_id": {"type": "string"}},
            "required": ["worktree_id"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Remove worktree", category="team", side_effect=ToolSideEffect.READ, parallel_safe=False
    )

    def run(self, arguments: JsonObject) -> ToolResult:
        try:
            lease = self.service.remove_worktree(
                scope=self.scope,
                permission_scope=self.permission_scope,
                worktree_id=_required(arguments, "worktree_id"),
            )
        except (ValueError, LookupError, PermissionError) as exc:
            return self.failure(arguments, _error(exc))
        return _result(self, arguments, {"worktree": _worktree_summary(lease)}, {"worktree_id": lease.worktree_id, "status": lease.status.value, "path_exposed": False})


def _result(tool: BaseTool, arguments: JsonObject, private: dict[str, Any], public: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_call_id=tool.call_id(arguments),
        name=tool.spec.name,
        content=json.dumps(private, ensure_ascii=False, sort_keys=True),
        public_content=json.dumps(public, ensure_ascii=False, sort_keys=True),
    )


def _schedule_summary(schedule: Any) -> dict[str, Any]:
    return {
        "schedule_id": schedule.schedule_id,
        "title": schedule.title,
        "kind": schedule.kind.value,
        "timezone": schedule.timezone,
        "status": schedule.status.value,
        "next_run_at": schedule.next_run_at,
        "last_scheduled_at": schedule.last_scheduled_at,
        "last_result": schedule.last_result,
    }


def _agent_summary(agent: Any) -> dict[str, Any]:
    return {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "role": agent.role,
        "kind": agent.kind.value,
        "status": agent.status.value,
        "parent_agent_id": agent.parent_agent_id,
        "parent_task_id": agent.parent_task_id,
        "child_task_id": agent.child_task_id,
    }


def _worktree_summary(lease: Any) -> dict[str, Any]:
    return {
        "worktree_id": lease.worktree_id,
        "agent_id": lease.agent_id,
        "task_id": lease.task_id,
        "branch_name": lease.branch_name,
        "base_ref": lease.base_ref,
        "status": lease.status.value,
        "head_sha": lease.head_sha,
        "error_code": lease.error_code,
    }


def _required(arguments: JsonObject, key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"{key}_required")
    return value.strip()


def _optional(arguments: JsonObject, key: str) -> str:
    value = arguments.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ToolInputError(f"{key}_must_be_string")
    return value.strip()


def _strings(arguments: JsonObject, key: str) -> tuple[str, ...]:
    value = arguments.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ToolInputError(f"{key}_must_be_string_array")
    return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))


def _integers(arguments: JsonObject, key: str) -> tuple[int, ...]:
    value = arguments.get(key, [])
    if not isinstance(value, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ToolInputError(f"{key}_must_be_integer_array")
    return tuple(value)


def _integer(arguments: JsonObject, key: str, *, default: int) -> int:
    value = arguments.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{key}_must_be_integer")
    return value


def _optional_integer(arguments: JsonObject, key: str) -> int | None:
    if key not in arguments:
        return None
    return _integer(arguments, key, default=0)


def _error(exc: Exception) -> str:
    value = str(exc).strip()
    if value.startswith(("task_", "schedule_", "team_", "permission_", "git_")):
        return value[:200]
    return type(exc).__name__
