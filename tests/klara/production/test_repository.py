from __future__ import annotations

from pathlib import Path

import pytest

from klara.production import Principal, ProductionRepository, QueueConflict, QueueLeaseError


def principal(tenant: str, user: str, *roles: str) -> Principal:
    return Principal(tenant, user, frozenset(roles or ("owner",)), "token-id", 2_000_000_000)


def test_migrations_owner_isolation_and_idempotency(tmp_path: Path) -> None:
    repository = ProductionRepository(tmp_path / "production.sqlite3")
    alice = principal("tenant-a", "alice", "owner", "operator")
    bob = principal("tenant-a", "bob", "owner", "operator")
    stranger = principal("tenant-b", "alice", "owner", "operator")
    session = repository.create_session(alice, title="Private")

    assert repository.migration_versions() == (1, 2, 3, 4)
    assert repository.get_session(alice, session["session_id"]) is not None
    assert repository.get_session(bob, session["session_id"]) is None
    assert repository.get_session(stranger, session["session_id"]) is None

    first, created = repository.enqueue_job(
        alice,
        session_id=session["session_id"],
        kind="agent.run",
        payload={"question": "bounded"},
        idempotency_key="request-0001",
        max_attempts=3,
    )
    repeated, created_again = repository.enqueue_job(
        alice,
        session_id=session["session_id"],
        kind="agent.run",
        payload={"question": "bounded"},
        idempotency_key="request-0001",
        max_attempts=3,
    )
    assert created is True
    assert created_again is False
    assert repeated["job_id"] == first["job_id"]
    assert repository.get_job(bob, first["job_id"]) is None
    assert repository.get_job(stranger, first["job_id"]) is None
    with pytest.raises(QueueConflict, match="idempotency_payload_mismatch"):
        repository.enqueue_job(
            alice,
            session_id=session["session_id"],
            kind="agent.run",
            payload={"question": "different"},
            idempotency_key="request-0001",
            max_attempts=3,
        )


def test_queue_lease_retry_outbox_and_secret_non_persistence(tmp_path: Path) -> None:
    clock = [1_700_000_000.0]
    path = tmp_path / "production.sqlite3"
    repository = ProductionRepository(path, clock=lambda: clock[0])
    owner = principal("tenant-a", "alice", "owner", "operator")
    worker = principal("tenant-a", "worker-1", "worker")
    session = repository.create_session(owner, title="Queue")
    job, _ = repository.enqueue_job(
        owner,
        session_id=session["session_id"],
        kind="agent.run",
        payload={"question": "hello"},
        idempotency_key="request-0002",
        max_attempts=2,
    )
    claim = repository.claim_next(worker, lease_seconds=30)
    assert claim and claim["job_id"] == job["job_id"]
    assert claim["payload"] == {"question": "hello"}
    token = claim["lease_token"]
    assert token.encode() not in path.read_bytes()
    with pytest.raises(QueueLeaseError):
        repository.heartbeat(worker, job_id=job["job_id"], lease_token="forged" * 8, lease_seconds=30)

    clock[0] += 31
    reclaimed = repository.claim_next(worker, lease_seconds=30)
    assert reclaimed and reclaimed["job_id"] == job["job_id"]
    completed = repository.complete(
        worker,
        job_id=job["job_id"],
        lease_token=reclaimed["lease_token"],
        result={"status": "ok"},
    )
    assert completed["state"] == "completed"
    events = repository.list_job_events(owner, job["job_id"])
    assert events and [event["event_type"] for event in events] == [
        "job.queued",
        "job.claimed",
        "job.lease_recovered",
        "job.claimed",
        "job.completed",
    ]
    assert all("question" not in str(event) for event in events)
    event = repository.claim_outbox(worker, lease_seconds=30)
    assert event and event["payload"] == {
        "job_id": job["job_id"],
        "run_id": job["run_id"],
        "state": "completed",
    }
    with pytest.raises(QueueLeaseError):
        repository.acknowledge_outbox(worker, event_id=event["event_id"], delivery_token="forged" * 8)
    delivered = repository.acknowledge_outbox(
        worker,
        event_id=event["event_id"],
        delivery_token=event["delivery_token"],
    )
    assert delivered["state"] == "delivered"


def test_queued_cancel_is_terminal_and_emits_outbox(tmp_path: Path) -> None:
    repository = ProductionRepository(tmp_path / "production.sqlite3")
    owner = principal("tenant-a", "alice", "owner")
    worker = principal("tenant-a", "worker-1", "worker")
    session = repository.create_session(owner, title="Cancel")
    job, _ = repository.enqueue_job(
        owner,
        session_id=session["session_id"],
        kind="agent.run",
        payload={},
        idempotency_key="request-0003",
        max_attempts=3,
    )
    cancelled = repository.cancel(owner, job["job_id"])
    assert cancelled and cancelled["state"] == "cancelled"
    assert repository.claim_next(worker, lease_seconds=30) is None
    event = repository.claim_outbox(worker, lease_seconds=30)
    assert event and event["event_type"] == "job.cancelled"


def test_backup_restore_integrity_retention_and_generic_state(tmp_path: Path) -> None:
    clock = [1_700_000_000.0]
    database = tmp_path / "production.sqlite3"
    repository = ProductionRepository(database, clock=lambda: clock[0])
    owner = principal("tenant-a", "alice", "owner")
    other = principal("tenant-a", "bob", "owner")
    session = repository.create_session(owner, title="Before backup")
    state = repository.put_state(
        owner,
        namespace="plan",
        record_id="plan-1",
        value={"status": "in_progress"},
        expected_version=0,
    )
    assert state["version"] == 1
    assert repository.get_state(other, namespace="plan", record_id="plan-1") is None
    with pytest.raises(QueueConflict, match="state_version_conflict"):
        repository.put_state(
            owner,
            namespace="plan",
            record_id="plan-1",
            value={"status": "completed"},
            expected_version=0,
        )
    updated = repository.put_state(
        owner,
        namespace="plan",
        record_id="plan-1",
        value={"status": "completed"},
        expected_version=1,
    )
    backup = repository.backup_to(tmp_path / "backup.sqlite3")
    assert backup["integrity"]["passed"] is True
    repository.create_session(owner, title="After backup")
    assert len(repository.list_sessions(owner)) == 2
    restored = repository.restore_from(tmp_path / "backup.sqlite3")
    assert restored["integrity"]["passed"] is True
    assert [item["title"] for item in repository.list_sessions(owner)] == ["Before backup"]
    assert repository.integrity_report()["passed"] is True
    assert repository.delete_state(owner, namespace="plan", record_id="plan-1", expected_version=updated["version"])
    assert repository.get_state(owner, namespace="plan", record_id="plan-1") is None

    job, _ = repository.enqueue_job(
        owner,
        session_id=session["session_id"],
        kind="agent.run",
        payload={"question": "redact later"},
        idempotency_key="retention-job",
        max_attempts=2,
    )
    assert repository.cancel(owner, job["job_id"])["state"] == "cancelled"
    worker = principal("tenant-a", "worker", "worker")
    outbox = repository.claim_outbox(worker, lease_seconds=30)
    repository.acknowledge_outbox(worker, event_id=outbox["event_id"], delivery_token=outbox["delivery_token"])
    clock[0] += 86400
    counts = repository.apply_retention(before_epoch=clock[0] - 1)
    assert counts["outbox_rows_deleted"] == 1
    assert counts["terminal_job_payloads_redacted"] == 1


def test_token_revocation_is_tenant_bound(tmp_path: Path) -> None:
    repository = ProductionRepository(tmp_path / "production.sqlite3")
    owner = principal("tenant-a", "alice", "owner")
    repository.revoke_token(owner, token_id="token-id-1", expires_at=2_000_000_000, reason="logout")
    assert repository.is_token_revoked("tenant-a", "token-id-1") is True
    assert repository.is_token_revoked("tenant-b", "token-id-1") is False
    assert b"token-id-1" not in (tmp_path / "production.sqlite3").read_bytes()
