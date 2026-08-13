from __future__ import annotations

import inspect

from klara.production.postgres_repository import PostgresProductionRepository, _POSTGRES_MIGRATIONS, _pg_job_event, _pg_outbox, _pg_state_record
from klara.production.repository import ProductionRepository


def test_postgres_adapter_implements_runtime_repository_surface() -> None:
    required = {
        "migrate", "migration_versions", "assert_schema_compatible", "create_session", "get_session", "list_sessions",
        "enqueue_job", "list_jobs", "get_job", "claim_next", "heartbeat", "complete", "fail", "cancel",
        "claim_outbox", "acknowledge_outbox", "list_job_events", "record_export", "audit", "audit_count",
        "revoke_token", "is_token_revoked", "put_state", "get_state", "delete_state", "apply_retention",
    }
    assert required.issubset(set(dir(PostgresProductionRepository)))
    assert required.issubset(set(dir(ProductionRepository)))


def test_postgres_queries_keep_locking_tenant_owner_and_jsonb_contracts() -> None:
    source = inspect.getsource(PostgresProductionRepository)
    migrations = "\n".join(statement for _, statements in _POSTGRES_MIGRATIONS for statement in statements)
    assert "LIMIT 1 FOR UPDATE SKIP LOCKED" in source
    assert "tenant_id = %s AND owner_id = %s" in source
    assert "ON CONFLICT" in source
    assert "BEGIN" not in source  # psycopg transaction context owns boundaries
    assert "JSONB" in migrations
    assert "UNIQUE(tenant_id, owner_id, idempotency_key)" in migrations
    assert "PRIMARY KEY(tenant_id, owner_id, namespace, record_id)" in migrations


def test_postgres_jsonb_rows_project_through_public_contracts() -> None:
    outbox = _pg_outbox({
        "event_id": "out-1", "tenant_id": "tenant", "owner_id": "owner", "job_id": "job-1",
        "event_type": "job.completed", "payload_json": {"state": "completed"}, "state": "pending",
        "attempts": 0, "created_at": "now", "delivered_at": None,
    })
    event = _pg_job_event({
        "event_id": "event-1", "job_id": "job-1", "run_id": "run-1", "seq": 1,
        "event_type": "job.queued", "payload_json": {"state": "queued"}, "created_at": "now",
    })
    state = _pg_state_record({
        "tenant_id": "tenant", "owner_id": "owner", "namespace": "plan", "record_id": "plan-1",
        "version": 1, "value_json": {"status": "pending"}, "value_sha256": "a" * 64,
        "created_at": "now", "updated_at": "now",
    })
    assert outbox["payload"] == {"state": "completed"}
    assert event["payload"] == {"state": "queued"}
    assert state["value"] == {"status": "pending"}
