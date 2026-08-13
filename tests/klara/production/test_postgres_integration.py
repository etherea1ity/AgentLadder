from __future__ import annotations

import os
from uuid import uuid4

import pytest

from klara.production import PostgresProductionRepository, Principal, QueueLeaseError


DSN = os.getenv("KLARA_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="KLARA_TEST_POSTGRES_DSN is not configured")


def _principal(tenant: str, user: str, *roles: str) -> Principal:
    return Principal(tenant, user, frozenset(roles), f"token-{tenant}-{user}", 2_000_000_000)


def test_postgres_real_migration_isolation_queue_outbox_and_jsonb() -> None:
    repository = PostgresProductionRepository(DSN)
    owner = _principal("tenant-a", "owner-a", "owner", "operator")
    other_owner = _principal("tenant-a", "owner-b", "owner")
    other_tenant = _principal("tenant-b", "owner-a", "owner")
    worker = _principal("tenant-a", "worker-a", "worker")
    session = repository.create_session(owner, title="PostgreSQL integration")
    assert repository.get_session(other_owner, session["session_id"]) is None
    assert repository.get_session(other_tenant, session["session_id"]) is None
    idempotency_key = f"postgres-integration-{uuid4().hex}"
    job, created = repository.enqueue_job(
        owner,
        session_id=session["session_id"],
        kind="agent.run",
        payload={"question": "What is 5 + 7?", "nested": {"value": 12}},
        idempotency_key=idempotency_key,
        max_attempts=3,
    )
    repeated, created_again = repository.enqueue_job(
        owner,
        session_id=session["session_id"],
        kind="agent.run",
        payload={"question": "What is 5 + 7?", "nested": {"value": 12}},
        idempotency_key=idempotency_key,
        max_attempts=3,
    )
    assert created and not created_again and repeated["job_id"] == job["job_id"]
    claim = repository.claim_next(worker, lease_seconds=60)
    assert claim and claim["payload"]["nested"] == {"value": 12}
    with pytest.raises(QueueLeaseError):
        repository.complete(worker, job_id=job["job_id"], lease_token="forged" * 8, result={})
    completed = repository.complete(
        worker,
        job_id=job["job_id"],
        lease_token=claim["lease_token"],
        result={"answer": "12", "usage": {"tokens": 5}},
    )
    assert completed["state"] == "completed"
    outbox = repository.claim_outbox(worker, lease_seconds=60)
    assert outbox and outbox["payload"]["state"] == "completed"
    assert repository.acknowledge_outbox(
        worker,
        event_id=outbox["event_id"],
        delivery_token=outbox["delivery_token"],
    )["state"] == "delivered"
    state = repository.put_state(
        owner,
        namespace="memory",
        record_id=f"memory-{uuid4().hex}",
        value={"kind": "preference", "content": "concise"},
        expected_version=0,
    )
    assert state["value"]["content"] == "concise"
    assert repository.get_state(other_owner, namespace="memory", record_id=state["record_id"]) is None
    repository.revoke_token(owner, token_id=owner.token_id, expires_at=owner.expires_at, reason="integration")
    assert repository.is_token_revoked(owner.tenant_id, owner.token_id)
    assert repository.is_token_revoked(other_tenant.tenant_id, owner.token_id) is False
