"""Deterministic lifecycle policy for durable tasks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from klara.tasks.models import (
    AttemptOutcome,
    DurableTask,
    EffectReservation,
    TaskArtifact,
    TaskAttempt,
    TaskCheckpoint,
    TaskClaim,
    TaskEvent,
    TaskScope,
    TaskState,
    new_artifact_id,
    new_attempt_id,
    new_checkpoint_id,
    new_event_id,
    new_task_id,
)
from klara.tasks.repository import SQLiteTaskRepository, TaskWriteConflict


class TaskNotFoundError(LookupError):
    pass


class TaskTransitionError(ValueError):
    pass


class TaskLeaseError(PermissionError):
    pass


class DurableTaskService:
    """Own task transitions; model prose cannot mutate lifecycle state."""

    MAX_LEASE_SECONDS = 3600
    MAX_ATTEMPTS = 8

    def __init__(
        self,
        repository: SQLiteTaskRepository,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def create(
        self,
        *,
        scope: TaskScope,
        title: str,
        description: str = "",
        dependency_ids: tuple[str, ...] = (),
        parent_task_id: str | None = None,
        required_artifacts: tuple[str, ...] = (),
        required_evidence: tuple[str, ...] = (),
        max_attempts: int = 3,
        task_id: str | None = None,
    ) -> DurableTask:
        title = " ".join(title.split())[:160]
        if not title:
            raise TaskTransitionError("task_title_required")
        if max_attempts < 1 or max_attempts > self.MAX_ATTEMPTS:
            raise TaskTransitionError("task_max_attempts_out_of_range")
        dependencies = tuple(dict.fromkeys(item.strip() for item in dependency_ids if item.strip()))
        parent = parent_task_id.strip() if parent_task_id else None
        for related_id in (*dependencies, *((parent,) if parent else ())):
            if self.repository.get_task(scope, related_id) is None:
                raise TaskTransitionError("task_related_record_not_found")
        identifier = task_id or new_task_id()
        if identifier in dependencies or identifier == parent:
            raise TaskTransitionError("task_cannot_depend_on_itself")
        now = self._now()
        state = TaskState.READY if self._dependencies_complete(scope, dependencies) else TaskState.WAITING
        task = DurableTask(
            task_id=identifier,
            scope=scope,
            title=title,
            description=" ".join(description.split())[:2000],
            state=state,
            dependency_ids=dependencies,
            parent_task_id=parent,
            required_artifacts=_clean_names(required_artifacts),
            required_evidence=_clean_names(required_evidence),
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
        )
        event = self._event(task, "created", None, state, details={"dependency_count": len(dependencies)})
        try:
            self.repository.create_task(task, event)
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                raise TaskTransitionError("task_id_already_exists") from None
            raise
        return task

    def get(self, *, scope: TaskScope, task_id: str) -> DurableTask:
        task = self.repository.get_task(scope, task_id)
        if task is None:
            raise TaskNotFoundError("task_not_found")
        return self._promote_waiting(task)

    def list(self, *, scope: TaskScope) -> list[DurableTask]:
        return [self._promote_waiting(task) for task in self.repository.list_tasks(scope)]

    def claim(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> TaskClaim:
        worker = worker_id.strip()[:120]
        if not worker:
            raise TaskTransitionError("task_worker_required")
        if lease_seconds < 1 or lease_seconds > self.MAX_LEASE_SECONDS:
            raise TaskTransitionError("task_lease_out_of_range")
        for _ in range(4):
            task = self.get(scope=scope, task_id=task_id)
            now_dt = self._now_dt()
            prior_attempt: TaskAttempt | None = None
            if task.state is TaskState.RUNNING:
                if task.lease_expires_at and _parse_time(task.lease_expires_at) > now_dt:
                    raise TaskLeaseError("task_already_claimed")
                prior_attempt = self._active_attempt(scope, task)
            elif task.state is not TaskState.READY:
                raise TaskTransitionError(f"task_cannot_claim_from_{task.state.value}")
            if task.attempt_count >= task.max_attempts:
                if prior_attempt is not None:
                    self._close_exhausted_expired_attempt(scope, task, prior_attempt)
                raise TaskTransitionError("task_attempt_budget_exhausted")
            now = now_dt.isoformat()
            lease_expires = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
            token = secrets.token_urlsafe(32)
            checkpoint = self.repository.latest_checkpoint(scope, task.task_id)
            attempt = TaskAttempt(
                attempt_id=new_attempt_id(),
                task_id=task.task_id,
                number=task.attempt_count + 1,
                worker_id=worker,
                outcome=AttemptOutcome.RUNNING,
                started_at=now,
                last_heartbeat_at=now,
                lease_expires_at=lease_expires,
                restored_checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
            )
            updated = replace(
                task,
                state=TaskState.RUNNING,
                active_attempt_id=attempt.attempt_id,
                attempt_count=attempt.number,
                lease_worker_id=worker,
                lease_token_sha256=_hash(token),
                lease_expires_at=lease_expires,
                heartbeat_at=now,
                block_reason=None,
                updated_at=now,
            )
            abandoned = (
                replace(
                    prior_attempt,
                    outcome=AttemptOutcome.ABANDONED,
                    ended_at=now,
                    failure_code="lease_expired",
                    failure_message="Worker lease expired before completion.",
                )
                if prior_attempt is not None
                else None
            )
            event = self._event(
                updated,
                "recovered" if prior_attempt else "claimed",
                task.state,
                TaskState.RUNNING,
                attempt_id=attempt.attempt_id,
                details={
                    "worker_id": worker,
                    "lease_expires_at": lease_expires,
                    "restored_checkpoint_id": attempt.restored_checkpoint_id,
                },
            )
            try:
                self.repository.save_transition(
                    scope=scope,
                    prior_updated_at=task.updated_at,
                    task=updated,
                    event=event,
                    new_attempt=attempt,
                    close_attempt=abandoned,
                )
                return TaskClaim(updated, token, checkpoint)
            except TaskWriteConflict:
                continue
        raise TaskWriteConflict("task_claim_contention")

    def heartbeat(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        lease_token: str,
        lease_seconds: int = 60,
    ) -> DurableTask:
        if lease_seconds < 1 or lease_seconds > self.MAX_LEASE_SECONDS:
            raise TaskTransitionError("task_lease_out_of_range")
        task, attempt = self._require_lease(scope, task_id, lease_token)
        now_dt = self._now_dt()
        now = now_dt.isoformat()
        expires = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        updated_attempt = replace(attempt, last_heartbeat_at=now, lease_expires_at=expires)
        updated = replace(task, heartbeat_at=now, lease_expires_at=expires, updated_at=now)
        self.repository.save_transition(
            scope=scope,
            prior_updated_at=task.updated_at,
            task=updated,
            event=self._event(updated, "heartbeat", task.state, task.state, attempt_id=attempt.attempt_id),
            update_attempt=updated_attempt,
        )
        return updated

    def progress(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        lease_token: str,
        progress: int,
        current_step: str,
    ) -> DurableTask:
        if progress < 0 or progress > 100:
            raise TaskTransitionError("task_progress_out_of_range")
        task, attempt = self._require_lease(scope, task_id, lease_token)
        if progress < task.progress:
            raise TaskTransitionError("task_progress_cannot_decrease")
        now = self._now()
        updated_attempt = replace(attempt, last_heartbeat_at=now)
        updated = replace(
            task,
            progress=progress,
            current_step=" ".join(current_step.split())[:240] or None,
            heartbeat_at=now,
            updated_at=now,
        )
        self.repository.save_transition(
            scope=scope,
            prior_updated_at=task.updated_at,
            task=updated,
            event=self._event(
                updated,
                "progressed",
                task.state,
                task.state,
                attempt_id=attempt.attempt_id,
                details={"progress": progress, "current_step": updated.current_step},
            ),
            update_attempt=updated_attempt,
        )
        return updated

    def checkpoint(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        lease_token: str,
        summary: str,
        payload: dict[str, object],
    ) -> TaskCheckpoint:
        task, attempt = self._require_lease(scope, task_id, lease_token)
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise TaskTransitionError("task_checkpoint_payload_not_json") from exc
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise TaskTransitionError("task_checkpoint_payload_too_large")
        normalized = json.loads(encoded)
        now = self._now()
        checkpoint = TaskCheckpoint(
            checkpoint_id=new_checkpoint_id(),
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            sequence=task.checkpoint_sequence + 1,
            summary=" ".join(summary.split())[:500],
            payload_sha256=_hash(encoded),
            payload_keys=tuple(sorted(str(key) for key in normalized)),
            created_at=now,
        )
        updated = replace(
            task,
            checkpoint_sequence=checkpoint.sequence,
            heartbeat_at=now,
            updated_at=now,
        )
        self.repository.save_checkpoint_transition(
            scope=scope,
            prior_updated_at=task.updated_at,
            task=updated,
            event=self._event(
                updated,
                "checkpointed",
                task.state,
                task.state,
                attempt_id=attempt.attempt_id,
                details=checkpoint.to_public_dict(),
            ),
            attempt=replace(attempt, last_heartbeat_at=now),
            checkpoint=checkpoint,
            payload=normalized,
        )
        return checkpoint

    def add_artifact(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        lease_token: str,
        name: str,
        uri: str,
        media_type: str,
        sha256: str,
        is_evidence: bool = False,
    ) -> TaskArtifact:
        task, attempt = self._require_lease(scope, task_id, lease_token)
        clean_name = " ".join(name.split())[:160]
        if not clean_name or not _is_sha256(sha256):
            raise TaskTransitionError("task_artifact_name_and_sha256_required")
        artifact = TaskArtifact(
            artifact_id=new_artifact_id(),
            task_id=task.task_id,
            name=clean_name,
            uri=_safe_uri(uri),
            media_type=media_type.strip()[:120] or "application/octet-stream",
            sha256=sha256.lower(),
            is_evidence=is_evidence,
            attempt_id=attempt.attempt_id,
            created_at=self._now(),
        )
        self.repository.append_artifact(scope, artifact)
        return artifact

    def reserve_effect(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        lease_token: str,
        idempotency_key: str,
    ) -> EffectReservation:
        task, attempt = self._require_lease(scope, task_id, lease_token)
        key = idempotency_key.strip()[:240]
        if not key:
            raise TaskTransitionError("task_idempotency_key_required")
        owner_attempt, status, result_sha256, result_payload, created = self.repository.reserve_effect(
            scope=scope,
            task_id=task.task_id,
            idempotency_key=key,
            attempt_id=attempt.attempt_id,
            created_at=self._now(),
        )
        return EffectReservation(
            task_id=task.task_id,
            idempotency_key=key,
            attempt_id=owner_attempt,
            status=status,
            should_execute=created,
            result_sha256=result_sha256,
            result_payload=result_payload,
        )

    def commit_effect(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        lease_token: str,
        idempotency_key: str,
        result_sha256: str,
        result_payload: dict[str, object] | None = None,
    ) -> EffectReservation:
        task, attempt = self._require_lease(scope, task_id, lease_token)
        if not _is_sha256(result_sha256):
            raise TaskTransitionError("task_effect_result_sha256_required")
        if result_payload is not None:
            try:
                encoded = json.dumps(
                    result_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise TaskTransitionError("task_effect_payload_not_json") from exc
            if len(encoded.encode("utf-8")) > 128 * 1024:
                raise TaskTransitionError("task_effect_payload_too_large")
        committed = self.repository.commit_effect(
            scope=scope,
            task_id=task.task_id,
            idempotency_key=idempotency_key,
            attempt_id=attempt.attempt_id,
            result_sha256=result_sha256.lower(),
            result_payload=result_payload,
            committed_at=self._now(),
        )
        if not committed:
            existing = self.reserve_effect(
                scope=scope,
                task_id=task_id,
                lease_token=lease_token,
                idempotency_key=idempotency_key,
            )
            if existing.status == "committed" and existing.result_sha256 == result_sha256.lower():
                return existing
            raise TaskTransitionError("task_effect_not_owned_or_already_committed")
        return EffectReservation(
            task_id=task.task_id,
            idempotency_key=idempotency_key,
            attempt_id=attempt.attempt_id,
            status="committed",
            should_execute=False,
            result_sha256=result_sha256.lower(),
            result_payload=result_payload,
        )

    def pause(self, *, scope: TaskScope, task_id: str, lease_token: str) -> DurableTask:
        return self._stop_attempt(scope, task_id, lease_token, TaskState.PAUSED, AttemptOutcome.PAUSED, "paused")

    def block(
        self, *, scope: TaskScope, task_id: str, lease_token: str, reason: str
    ) -> DurableTask:
        return self._stop_attempt(
            scope,
            task_id,
            lease_token,
            TaskState.BLOCKED,
            AttemptOutcome.BLOCKED,
            "blocked",
            block_reason=" ".join(reason.split())[:500] or "blocked",
        )

    def fail(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        lease_token: str,
        code: str,
        message: str,
    ) -> DurableTask:
        return self._stop_attempt(
            scope,
            task_id,
            lease_token,
            TaskState.FAILED,
            AttemptOutcome.FAILED,
            "failed",
            failure_code=code[:120],
            failure_message=" ".join(message.split())[:500],
        )

    def complete(
        self, *, scope: TaskScope, task_id: str, lease_token: str
    ) -> DurableTask:
        task, attempt = self._require_lease(scope, task_id, lease_token)
        artifacts = self.repository.list_artifacts(scope, task.task_id)
        artifact_names = {item.name for item in artifacts}
        evidence_names = {item.name for item in artifacts if item.is_evidence}
        missing_artifacts = sorted(set(task.required_artifacts) - artifact_names)
        missing_evidence = sorted(set(task.required_evidence) - evidence_names)
        if missing_artifacts or missing_evidence:
            raise TaskTransitionError(
                "task_completion_requirements_missing:"
                + json.dumps(
                    {"artifacts": missing_artifacts, "evidence": missing_evidence},
                    separators=(",", ":"),
                )
            )
        return self._finish(
            scope,
            task,
            attempt,
            state=TaskState.COMPLETED,
            outcome=AttemptOutcome.COMPLETED,
            operation="completed",
            progress=100,
        )

    def resume(self, *, scope: TaskScope, task_id: str) -> DurableTask:
        task = self.get(scope=scope, task_id=task_id)
        if task.state not in {TaskState.PAUSED, TaskState.BLOCKED}:
            raise TaskTransitionError(f"task_cannot_resume_from_{task.state.value}")
        state = TaskState.READY if self._dependencies_complete(scope, task.dependency_ids) else TaskState.WAITING
        now = self._now()
        updated = replace(task, state=state, block_reason=None, updated_at=now)
        self.repository.save_transition(
            scope=scope,
            prior_updated_at=task.updated_at,
            task=updated,
            event=self._event(updated, "resumed", task.state, state),
        )
        return updated

    def retry(self, *, scope: TaskScope, task_id: str) -> DurableTask:
        task = self.get(scope=scope, task_id=task_id)
        if task.state is not TaskState.FAILED:
            raise TaskTransitionError(f"task_cannot_retry_from_{task.state.value}")
        if task.attempt_count >= task.max_attempts:
            raise TaskTransitionError("task_attempt_budget_exhausted")
        state = TaskState.READY if self._dependencies_complete(scope, task.dependency_ids) else TaskState.WAITING
        now = self._now()
        updated = replace(task, state=state, block_reason=None, updated_at=now)
        self.repository.save_transition(
            scope=scope,
            prior_updated_at=task.updated_at,
            task=updated,
            event=self._event(updated, "retried", task.state, state),
        )
        return updated

    def cancel(self, *, scope: TaskScope, task_id: str) -> DurableTask:
        task = self.get(scope=scope, task_id=task_id)
        if task.state in {TaskState.COMPLETED, TaskState.CANCELLED}:
            return task
        if task.state is TaskState.RUNNING:
            attempt = self._active_attempt(scope, task)
            updated = self._finish(
                scope,
                task,
                attempt,
                state=TaskState.CANCELLED,
                outcome=AttemptOutcome.CANCELLED,
                operation="cancelled",
            )
        else:
            now = self._now()
            updated = replace(
                task,
                state=TaskState.CANCELLED,
                active_attempt_id=None,
                cancelled_at=now,
                updated_at=now,
            )
            self.repository.save_transition(
                scope=scope,
                prior_updated_at=task.updated_at,
                task=updated,
                event=self._event(updated, "cancelled", task.state, TaskState.CANCELLED),
            )
        for child in self.repository.list_tasks(scope):
            if child.parent_task_id == task.task_id and child.state not in {
                TaskState.COMPLETED,
                TaskState.CANCELLED,
            }:
                self.cancel(scope=scope, task_id=child.task_id)
        return updated

    def detail(self, *, scope: TaskScope, task_id: str) -> dict[str, object]:
        task = self.get(scope=scope, task_id=task_id)
        checkpoint = self.repository.latest_checkpoint(scope, task.task_id)
        return {
            "schema_version": "klara.durable-task-detail.v1",
            "task": task.to_public_dict(),
            "attempts": [item.to_public_dict() for item in self.repository.list_attempts(scope, task.task_id)],
            "artifacts": [item.to_public_dict() for item in self.repository.list_artifacts(scope, task.task_id)],
            "latest_checkpoint": checkpoint.to_public_dict() if checkpoint else None,
            "events": [item.to_public_dict() for item in self.repository.list_events(scope, task.task_id)],
        }

    def _stop_attempt(
        self,
        scope: TaskScope,
        task_id: str,
        lease_token: str,
        state: TaskState,
        outcome: AttemptOutcome,
        operation: str,
        *,
        block_reason: str | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> DurableTask:
        task, attempt = self._require_lease(scope, task_id, lease_token)
        return self._finish(
            scope,
            task,
            attempt,
            state=state,
            outcome=outcome,
            operation=operation,
            block_reason=block_reason,
            failure_code=failure_code,
            failure_message=failure_message,
        )

    def _close_exhausted_expired_attempt(
        self, scope: TaskScope, task: DurableTask, attempt: TaskAttempt
    ) -> None:
        """Turn an unrecoverable expired final attempt into an auditable failure."""

        now = self._now()
        closed = replace(
            attempt,
            outcome=AttemptOutcome.ABANDONED,
            ended_at=now,
            failure_code="lease_expired_attempt_budget_exhausted",
            failure_message="Worker lease expired and no retry attempt remains.",
        )
        failed = replace(
            task,
            state=TaskState.FAILED,
            active_attempt_id=None,
            lease_worker_id=None,
            lease_token_sha256=None,
            lease_expires_at=None,
            heartbeat_at=now,
            block_reason="Attempt budget exhausted after lease expiry.",
            updated_at=now,
        )
        self.repository.save_transition(
            scope=scope,
            prior_updated_at=task.updated_at,
            task=failed,
            event=self._event(
                failed,
                "lease_expired_attempt_budget_exhausted",
                TaskState.RUNNING,
                TaskState.FAILED,
                attempt_id=attempt.attempt_id,
            ),
            close_attempt=closed,
        )

    def _finish(
        self,
        scope: TaskScope,
        task: DurableTask,
        attempt: TaskAttempt,
        *,
        state: TaskState,
        outcome: AttemptOutcome,
        operation: str,
        progress: int | None = None,
        block_reason: str | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> DurableTask:
        now = self._now()
        closed = replace(
            attempt,
            outcome=outcome,
            ended_at=now,
            last_heartbeat_at=now,
            failure_code=failure_code,
            failure_message=failure_message,
        )
        updated = replace(
            task,
            state=state,
            active_attempt_id=None,
            progress=task.progress if progress is None else progress,
            block_reason=block_reason,
            lease_worker_id=None,
            lease_token_sha256=None,
            lease_expires_at=None,
            heartbeat_at=now,
            updated_at=now,
            completed_at=now if state is TaskState.COMPLETED else task.completed_at,
            cancelled_at=now if state is TaskState.CANCELLED else task.cancelled_at,
        )
        self.repository.save_transition(
            scope=scope,
            prior_updated_at=task.updated_at,
            task=updated,
            event=self._event(updated, operation, task.state, state, attempt_id=attempt.attempt_id),
            close_attempt=closed,
        )
        return updated

    def _require_lease(
        self, scope: TaskScope, task_id: str, lease_token: str
    ) -> tuple[DurableTask, TaskAttempt]:
        task = self.get(scope=scope, task_id=task_id)
        if task.state is not TaskState.RUNNING or not task.active_attempt_id:
            raise TaskLeaseError("task_not_running")
        if not secrets.compare_digest(task.lease_token_sha256 or "", _hash(lease_token)):
            raise TaskLeaseError("task_lease_token_invalid")
        if not task.lease_expires_at or _parse_time(task.lease_expires_at) <= self._now_dt():
            raise TaskLeaseError("task_lease_expired")
        return task, self._active_attempt(scope, task)

    def _active_attempt(self, scope: TaskScope, task: DurableTask) -> TaskAttempt:
        attempt = (
            self.repository.get_attempt(scope, task.active_attempt_id)
            if task.active_attempt_id
            else None
        )
        if attempt is None or attempt.outcome is not AttemptOutcome.RUNNING:
            raise TaskLeaseError("task_active_attempt_missing")
        return attempt

    def _promote_waiting(self, task: DurableTask) -> DurableTask:
        if task.state is not TaskState.WAITING or not self._dependencies_complete(task.scope, task.dependency_ids):
            return task
        now = self._now()
        updated = replace(task, state=TaskState.READY, updated_at=now)
        try:
            self.repository.save_transition(
                scope=task.scope,
                prior_updated_at=task.updated_at,
                task=updated,
                event=self._event(updated, "dependencies_satisfied", task.state, TaskState.READY),
            )
            return updated
        except TaskWriteConflict:
            return self.repository.get_task(task.scope, task.task_id) or task

    def _dependencies_complete(self, scope: TaskScope, ids: tuple[str, ...]) -> bool:
        return all(
            (dependency := self.repository.get_task(scope, task_id)) is not None
            and dependency.state is TaskState.COMPLETED
            for task_id in ids
        )

    def _event(
        self,
        task: DurableTask,
        operation: str,
        from_state: TaskState | None,
        to_state: TaskState,
        *,
        attempt_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> TaskEvent:
        return TaskEvent(
            event_id=new_event_id(),
            task_id=task.task_id,
            operation=operation,
            from_state=from_state.value if from_state else None,
            to_state=to_state.value,
            occurred_at=self._now(),
            attempt_id=attempt_id,
            details=dict(details or {}),
        )

    def _now_dt(self) -> datetime:
        value = self._now_fn()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def _now(self) -> str:
        return self._now_dt().isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _clean_names(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(" ".join(value.split())[:160] for value in values if value.strip()))


def _safe_uri(value: str) -> str:
    uri = value.strip()[:2048]
    if not uri:
        raise TaskTransitionError("task_artifact_uri_required")
    parsed = urlsplit(uri)
    if parsed.scheme in {"http", "https"}:
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", ""))
    if parsed.scheme in {"artifact", "workspace"}:
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))
    if parsed.scheme and parsed.scheme not in {"artifact", "workspace"}:
        raise TaskTransitionError("task_artifact_uri_scheme_not_allowed")
    return uri
