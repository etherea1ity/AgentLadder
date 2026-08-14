from __future__ import annotations

from dataclasses import dataclass

from klara.core.tools import JsonObject, ToolCall, ToolMetadata, ToolResult, ToolSideEffect, ToolSpec
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope
from klara.tasks.tool_executor import DurableToolExecutor


@dataclass
class _WriteTool:
    calls: int = 0
    spec: ToolSpec = ToolSpec("write_probe", "Write once.", {"type": "object"})
    metadata: ToolMetadata = ToolMetadata(
        label="Write probe",
        category="test",
        side_effect=ToolSideEffect.WRITE,
        parallel_safe=False,
    )

    def execute(self, arguments: JsonObject) -> ToolResult:
        self.calls += 1
        return ToolResult("concrete", "write_probe", f"wrote:{arguments['value']}")


def test_committed_write_result_is_replayed_without_duplicate_execution(tmp_path) -> None:
    service = DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3"))
    scope = TaskScope(tenant_id="tenant", owner_id="owner")
    task = service.create(scope=scope, title="durable tool")
    claim = service.claim(scope=scope, task_id=task.task_id, worker_id="worker")
    tool = _WriteTool()
    executor = DurableToolExecutor(
        [tool], task_service=service, scope=scope, task_id=task.task_id,
        lease_token=claim.lease_token,
    )

    first = executor.execute(ToolCall("call-1", "write_probe", {"value": 7}))
    replay = executor.execute(ToolCall("call-2", "write_probe", {"value": 7}))

    assert first.ok and replay.ok
    assert replay.tool_call_id == "call-2"
    assert replay.content == "wrote:7"
    assert tool.calls == 1


def test_uncommitted_reservation_blocks_uncertain_duplicate(tmp_path) -> None:
    service = DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3"))
    scope = TaskScope(tenant_id="tenant", owner_id="owner")
    task = service.create(scope=scope, title="uncertain tool")
    claim = service.claim(scope=scope, task_id=task.task_id, worker_id="worker")
    tool = _WriteTool()
    executor = DurableToolExecutor(
        [tool], task_service=service, scope=scope, task_id=task.task_id,
        lease_token=claim.lease_token,
    )
    from klara.tasks.tool_executor import _effect_key

    call = ToolCall("call-2", "write_probe", {"value": 8})
    service.reserve_effect(
        scope=scope, task_id=task.task_id, lease_token=claim.lease_token,
        idempotency_key=_effect_key(call),
    )

    result = executor.execute(call)

    assert not result.ok
    assert result.error == "tool_effect_outcome_unknown"
    assert tool.calls == 0
