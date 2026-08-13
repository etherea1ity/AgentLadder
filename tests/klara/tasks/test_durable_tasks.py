from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from klara.tasks import (
    AttemptOutcome,
    DurableTaskService,
    SQLiteTaskRepository,
    TaskLeaseError,
    TaskNotFoundError,
    TaskScope,
    TaskState,
    TaskTransitionError,
)


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        self.value += timedelta(microseconds=1)
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def runtime(tmp_path: Path):
    clock = Clock()
    repository = SQLiteTaskRepository(tmp_path / "tasks.sqlite3")
    return clock, repository, DurableTaskService(repository, now_fn=clock.now)


def scope(owner: str = "alice", tenant: str = "tenant-a") -> TaskScope:
    return TaskScope(tenant_id=tenant, owner_id=owner)


def test_complete_lifecycle_keeps_attempt_checkpoint_artifact_and_events(runtime) -> None:
    _, repository, service = runtime
    task = service.create(
        scope=scope(),
        title="Prepare verified report",
        required_artifacts=("report",),
        required_evidence=("sources",),
    )
    claim = service.claim(scope=scope(), task_id=task.task_id, worker_id="worker-1")
    service.progress(
        scope=scope(),
        task_id=task.task_id,
        lease_token=claim.lease_token,
        progress=40,
        current_step="Verify sources",
    )
    checkpoint = service.checkpoint(
        scope=scope(),
        task_id=task.task_id,
        lease_token=claim.lease_token,
        summary="Source verification complete",
        payload={"source_ids": ["s1"], "secret": "stored, never public"},
    )
    service.add_artifact(
        scope=scope(),
        task_id=task.task_id,
        lease_token=claim.lease_token,
        name="report",
        uri="workspace://reports/final.md?token=hidden",
        media_type="text/markdown",
        sha256="a" * 64,
    )
    with pytest.raises(TaskTransitionError, match="requirements_missing"):
        service.complete(scope=scope(), task_id=task.task_id, lease_token=claim.lease_token)
    service.add_artifact(
        scope=scope(),
        task_id=task.task_id,
        lease_token=claim.lease_token,
        name="sources",
        uri="https://example.com/evidence?secret=removed",
        media_type="application/json",
        sha256="b" * 64,
        is_evidence=True,
    )
    completed = service.complete(
        scope=scope(), task_id=task.task_id, lease_token=claim.lease_token
    )
    detail = service.detail(scope=scope(), task_id=task.task_id)
    assert completed.state is TaskState.COMPLETED
    assert completed.progress == 100
    assert detail["latest_checkpoint"]["checkpoint_id"] == checkpoint.checkpoint_id
    assert detail["attempts"][0]["outcome"] == "completed"
    assert [event["operation"] for event in detail["events"]] == [
        "created",
        "claimed",
        "progressed",
        "checkpointed",
        "completed",
    ]
    assert "secret" not in str(detail)
    assert repository.checkpoint_payload(scope(), checkpoint.checkpoint_id)["secret"] == "stored, never public"


def test_expired_lease_recovers_checkpoint_and_abandons_attempt(runtime) -> None:
    clock, repository, service = runtime
    task = service.create(scope=scope(), title="Recover me", max_attempts=3)
    first = service.claim(
        scope=scope(), task_id=task.task_id, worker_id="dead-worker", lease_seconds=5
    )
    checkpoint = service.checkpoint(
        scope=scope(),
        task_id=task.task_id,
        lease_token=first.lease_token,
        summary="Before process death",
        payload={"cursor": 17},
    )
    clock.advance(6)
    second = service.claim(
        scope=scope(), task_id=task.task_id, worker_id="recovery-worker"
    )
    attempts = repository.list_attempts(scope(), task.task_id)
    assert second.restored_checkpoint == checkpoint
    assert second.task.attempt_count == 2
    assert attempts[0].outcome is AttemptOutcome.ABANDONED
    assert attempts[1].outcome is AttemptOutcome.RUNNING
    with pytest.raises(TaskLeaseError):
        service.progress(
            scope=scope(),
            task_id=task.task_id,
            lease_token=first.lease_token,
            progress=80,
            current_step="stale worker",
        )


def test_effect_receipt_prevents_duplicate_execution_after_recovery(runtime) -> None:
    clock, _, service = runtime
    task = service.create(scope=scope(), title="External side effect")
    first = service.claim(scope=scope(), task_id=task.task_id, worker_id="w1", lease_seconds=2)
    reservation = service.reserve_effect(
        scope=scope(),
        task_id=task.task_id,
        lease_token=first.lease_token,
        idempotency_key="send:invoice-42",
    )
    assert reservation.should_execute
    service.commit_effect(
        scope=scope(),
        task_id=task.task_id,
        lease_token=first.lease_token,
        idempotency_key="send:invoice-42",
        result_sha256="c" * 64,
    )
    clock.advance(3)
    recovered = service.claim(scope=scope(), task_id=task.task_id, worker_id="w2")
    replay = service.reserve_effect(
        scope=scope(),
        task_id=task.task_id,
        lease_token=recovered.lease_token,
        idempotency_key="send:invoice-42",
    )
    assert replay.status == "committed"
    assert replay.result_sha256 == "c" * 64
    assert not replay.should_execute


def test_dependencies_promote_only_after_parent_completion(runtime) -> None:
    _, _, service = runtime
    first = service.create(scope=scope(), title="First")
    second = service.create(
        scope=scope(), title="Second", dependency_ids=(first.task_id,)
    )
    assert second.state is TaskState.WAITING
    with pytest.raises(TaskTransitionError, match="cannot_claim"):
        service.claim(scope=scope(), task_id=second.task_id, worker_id="w")
    claim = service.claim(scope=scope(), task_id=first.task_id, worker_id="w")
    service.complete(scope=scope(), task_id=first.task_id, lease_token=claim.lease_token)
    assert service.get(scope=scope(), task_id=second.task_id).state is TaskState.READY


def test_cancel_propagates_to_descendants_and_preserves_closed_attempt(runtime) -> None:
    _, repository, service = runtime
    parent = service.create(scope=scope(), title="Parent")
    child = service.create(scope=scope(), title="Child", parent_task_id=parent.task_id)
    grandchild = service.create(scope=scope(), title="Grandchild", parent_task_id=child.task_id)
    claim = service.claim(scope=scope(), task_id=child.task_id, worker_id="w")
    service.cancel(scope=scope(), task_id=parent.task_id)
    assert service.get(scope=scope(), task_id=parent.task_id).state is TaskState.CANCELLED
    assert service.get(scope=scope(), task_id=child.task_id).state is TaskState.CANCELLED
    assert service.get(scope=scope(), task_id=grandchild.task_id).state is TaskState.CANCELLED
    attempts = repository.list_attempts(scope(), child.task_id)
    assert attempts == [
        attempts[0]
    ] and attempts[0].attempt_id == claim.task.active_attempt_id
    assert attempts[0].outcome is AttemptOutcome.CANCELLED


def test_pause_resume_block_fail_retry_and_attempt_budget(runtime) -> None:
    _, repository, service = runtime
    task = service.create(scope=scope(), title="Transitions", max_attempts=3)
    first = service.claim(scope=scope(), task_id=task.task_id, worker_id="w1")
    paused = service.pause(scope=scope(), task_id=task.task_id, lease_token=first.lease_token)
    assert paused.state is TaskState.PAUSED
    service.resume(scope=scope(), task_id=task.task_id)
    second = service.claim(scope=scope(), task_id=task.task_id, worker_id="w2")
    blocked = service.block(
        scope=scope(), task_id=task.task_id, lease_token=second.lease_token, reason="Need approval"
    )
    assert blocked.block_reason == "Need approval"
    service.resume(scope=scope(), task_id=task.task_id)
    third = service.claim(scope=scope(), task_id=task.task_id, worker_id="w3")
    failed = service.fail(
        scope=scope(), task_id=task.task_id, lease_token=third.lease_token, code="boom", message="failed"
    )
    assert failed.state is TaskState.FAILED
    with pytest.raises(TaskTransitionError, match="budget_exhausted"):
        service.retry(scope=scope(), task_id=task.task_id)
    assert [attempt.outcome for attempt in repository.list_attempts(scope(), task.task_id)] == [
        AttemptOutcome.PAUSED,
        AttemptOutcome.BLOCKED,
        AttemptOutcome.FAILED,
    ]


def test_tenant_and_owner_isolation_is_indistinguishable_from_missing(runtime) -> None:
    _, _, service = runtime
    task = service.create(scope=scope(), title="Private")
    for attacker in (scope(owner="mallory"), scope(tenant="tenant-b")):
        with pytest.raises(TaskNotFoundError):
            service.get(scope=attacker, task_id=task.task_id)
        assert service.list(scope=attacker) == []


def test_wrong_and_expired_lease_cannot_mutate(runtime) -> None:
    clock, _, service = runtime
    task = service.create(scope=scope(), title="Lease checks")
    claim = service.claim(scope=scope(), task_id=task.task_id, worker_id="w", lease_seconds=2)
    with pytest.raises(TaskLeaseError, match="invalid"):
        service.heartbeat(scope=scope(), task_id=task.task_id, lease_token="wrong")
    clock.advance(3)
    with pytest.raises(TaskLeaseError, match="expired"):
        service.checkpoint(
            scope=scope(), task_id=task.task_id, lease_token=claim.lease_token, summary="late", payload={}
        )


def test_expired_final_attempt_closes_failed_instead_of_staying_stale(runtime) -> None:
    clock, repository, service = runtime
    task = service.create(scope=scope(), title="Final attempt", max_attempts=1)
    service.claim(
        scope=scope(), task_id=task.task_id, worker_id="dead", lease_seconds=2
    )
    clock.advance(3)
    with pytest.raises(TaskTransitionError, match="budget_exhausted"):
        service.claim(scope=scope(), task_id=task.task_id, worker_id="late")
    failed = service.get(scope=scope(), task_id=task.task_id)
    attempts = repository.list_attempts(scope(), task.task_id)
    assert failed.state is TaskState.FAILED
    assert failed.active_attempt_id is None
    assert attempts[0].outcome is AttemptOutcome.ABANDONED


def test_artifact_uri_removes_web_query_and_rejects_unsafe_scheme(runtime) -> None:
    _, repository, service = runtime
    task = service.create(scope=scope(), title="Artifact URI")
    claim = service.claim(scope=scope(), task_id=task.task_id, worker_id="w")
    artifact = service.add_artifact(
        scope=scope(), task_id=task.task_id, lease_token=claim.lease_token,
        name="source", uri="HTTPS://Example.COM/a?token=secret#x", media_type="text/plain", sha256="d" * 64,
    )
    assert artifact.uri == "https://example.com/a"
    with pytest.raises(TaskTransitionError, match="scheme_not_allowed"):
        service.add_artifact(
            scope=scope(), task_id=task.task_id, lease_token=claim.lease_token,
            name="bad", uri="file:///etc/passwd", media_type="text/plain", sha256="e" * 64,
        )
    assert len(repository.list_artifacts(scope(), task.task_id)) == 1


def test_checkpoint_and_hash_inputs_are_bounded(runtime) -> None:
    _, _, service = runtime
    task = service.create(scope=scope(), title="Bounded inputs")
    claim = service.claim(scope=scope(), task_id=task.task_id, worker_id="w")
    with pytest.raises(TaskTransitionError, match="payload_too_large"):
        service.checkpoint(
            scope=scope(), task_id=task.task_id, lease_token=claim.lease_token,
            summary="large", payload={"content": "x" * (256 * 1024)},
        )
    with pytest.raises(TaskTransitionError, match="sha256_required"):
        service.add_artifact(
            scope=scope(), task_id=task.task_id, lease_token=claim.lease_token,
            name="invalid", uri="artifact://invalid", media_type="text/plain", sha256="z" * 64,
        )
