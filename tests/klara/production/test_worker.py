from __future__ import annotations

from pathlib import Path

from klara.production import Principal, ProductionQueueWorker, ProductionRepository


def _principal(user: str, *roles: str) -> Principal:
    return Principal("tenant-a", user, frozenset(roles), "token", 2_000_000_000)


def test_worker_executes_one_production_job_and_emits_outbox(tmp_path: Path) -> None:
    repository = ProductionRepository(tmp_path / "production.sqlite3")
    owner = _principal("alice", "owner", "operator")
    worker_principal = _principal("worker", "worker")
    session = repository.create_session(owner, title="Runtime")
    job, _ = repository.enqueue_job(
        owner,
        session_id=session["session_id"],
        kind="agent.run",
        payload={"question": "What is the bounded result?"},
        idempotency_key="worker-run-0001",
        max_attempts=3,
    )
    observed = []

    def executor(payload, context):
        observed.append((payload, context))
        assert context.cancel_requested is False
        context.heartbeat()
        return {"status": "completed", "answer_sha256": "a" * 64}

    worker = ProductionQueueWorker(repository, worker_principal, executor, lease_seconds=60)
    result = worker.run_once()
    assert result and result["state"] == "completed"
    assert observed[0][0]["question"] == "What is the bounded result?"
    assert observed[0][1].run_id == job["run_id"]
    assert repository.claim_outbox(worker_principal, lease_seconds=60) is not None


def test_worker_retries_executor_failure_without_exposing_error_text(tmp_path: Path) -> None:
    repository = ProductionRepository(tmp_path / "production.sqlite3")
    owner = _principal("alice", "owner")
    worker_principal = _principal("worker", "worker")
    session = repository.create_session(owner, title="Retry")
    job, _ = repository.enqueue_job(
        owner,
        session_id=session["session_id"],
        kind="agent.run",
        payload={},
        idempotency_key="worker-run-0002",
        max_attempts=3,
    )

    def fail(_payload, _context):
        raise RuntimeError("private provider text must not persist")

    result = ProductionQueueWorker(repository, worker_principal, fail, lease_seconds=60).run_once()
    assert result and result["state"] == "queued"
    assert result["error_code"] == "RuntimeError"
    assert "private provider text" not in (tmp_path / "production.sqlite3").read_bytes().decode("utf-8", errors="ignore")
    events = repository.list_job_events(owner, job["job_id"])
    assert events and events[-1]["event_type"] == "job.retry_scheduled"
