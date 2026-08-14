"""Durable tool execution receipts for mutating Agent runs."""

from __future__ import annotations

import hashlib
import json

from klara.core.tools import KlaraTool, ToolCall, ToolResult, ToolSideEffect
from klara.tasks.models import TaskScope
from klara.tasks.service import DurableTaskService, TaskTransitionError
from klara.tools.executor import ToolExecutor


class DurableToolExecutor(ToolExecutor):
    """Prevent duplicate write/control effects across worker recovery.

    A committed result is replayed from the private task journal. A reservation
    without a receipt means the previous worker may have performed the effect;
    the executor therefore returns an explicit uncertainty error instead of
    risking a duplicate mutation.
    """

    def __init__(
        self,
        tools: list[KlaraTool],
        *,
        task_service: DurableTaskService,
        scope: TaskScope,
        task_id: str,
        lease_token: str,
    ) -> None:
        super().__init__(tools)
        self._task_service = task_service
        self._scope = scope
        self._task_id = task_id
        self._lease_token = lease_token

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None or tool.metadata.side_effect not in {
            ToolSideEffect.WRITE,
            ToolSideEffect.CONTROL,
        }:
            return super().execute(call)

        key = _effect_key(call)
        try:
            reservation = self._task_service.reserve_effect(
                scope=self._scope,
                task_id=self._task_id,
                lease_token=self._lease_token,
                idempotency_key=key,
            )
        except TaskTransitionError as exc:
            return _uncertain_result(call, f"effect_reservation_failed:{exc}")

        if not reservation.should_execute:
            if reservation.status == "committed" and reservation.result_payload:
                return _result_from_payload(call, reservation.result_payload)
            return _uncertain_result(call, "tool_effect_outcome_unknown")

        result = super().execute(call)
        payload = {
            "tool_call_id": result.tool_call_id,
            "name": result.name,
            "content": result.content,
            "ok": result.ok,
            "error": result.error,
            "public_content": result.public_content,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        try:
            self._task_service.commit_effect(
                scope=self._scope,
                task_id=self._task_id,
                lease_token=self._lease_token,
                idempotency_key=key,
                result_sha256=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                result_payload=payload,
            )
        except TaskTransitionError:
            # The current call still receives its observation. Recovery will see
            # the unresolved reservation and refuse to repeat the side effect.
            pass
        return result


def _effect_key(call: ToolCall) -> str:
    canonical = json.dumps(
        {"name": call.name, "arguments": call.arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return f"tool:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _result_from_payload(call: ToolCall, payload: dict[str, object]) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        name=call.name,
        content=str(payload.get("content", "")),
        ok=bool(payload.get("ok", False)),
        error=str(payload["error"]) if payload.get("error") is not None else None,
        public_content=(
            str(payload["public_content"])
            if payload.get("public_content") is not None
            else None
        ),
    )


def _uncertain_result(call: ToolCall, error: str) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        name=call.name,
        content="",
        ok=False,
        error=error,
        public_content="The tool was not repeated because its prior outcome is uncertain.",
    )
