"""PostgreSQL production adapter with the same tenant, lease, and Outbox contract."""

from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import secrets
import time
from typing import Any, Iterator
from uuid import uuid4

from klara.production.auth import Principal
from klara.production.repository import (
    QueueConflict,
    QueueLeaseError,
    _canonical,
    _hash,
    _iso,
    _job,
    _job_event,
    _outbox,
    _session,
    _state_record,
    _validate_state_identity,
    hmac_compare,
)


class PostgresProductionRepository:
    """PostgreSQL adapter for multi-worker deployments.

    The driver is an optional dependency. All selection and mutation queries
    retain explicit tenant/owner predicates; queue claims add `FOR UPDATE SKIP
    LOCKED` so workers do not serialize behind an already claimed row.
    """

    def __init__(self, dsn: str, *, clock=time.time, connect=None) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN is required")
        if connect is None:
            try:
                psycopg = importlib.import_module("psycopg")
                rows = importlib.import_module("psycopg.rows")
            except ImportError as exc:
                raise RuntimeError(
                    "Install the production-postgres extra to use PostgreSQL"
                ) from exc
            connect = lambda: psycopg.connect(dsn, row_factory=rows.dict_row)
        self._connect_factory = connect
        self._clock = clock
        self.migrate()

    def migrate(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL)"
            )
            for version, statements in _POSTGRES_MIGRATIONS:
                checksum = _hash("\n".join(statements))
                existing = connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version = %s FOR UPDATE",
                    (version,),
                ).fetchone()
                if existing:
                    if existing["checksum"] != checksum:
                        raise RuntimeError(f"migration checksum mismatch for version {version}")
                    continue
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (%s, %s, %s)",
                    (version, checksum, _iso(self._clock())),
                )

    def migration_versions(self) -> tuple[int, ...]:
        with self._connection() as connection:
            rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        return tuple(int(row["version"]) for row in rows)

    def assert_schema_compatible(self) -> None:
        expected = tuple(version for version, _ in _POSTGRES_MIGRATIONS)
        if self.migration_versions() != expected:
            raise RuntimeError("PostgreSQL schema is not at the supported forward-only version")

    def create_session(self, principal: Principal, *, title: str) -> dict[str, Any]:
        session_id = f"psess_{uuid4().hex}"
        now = _iso(self._clock())
        with self._transaction() as connection:
            row = connection.execute(
                "INSERT INTO prod_sessions(session_id, tenant_id, owner_id, title, status, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, 'active', %s, %s) RETURNING *",
                (session_id, principal.tenant_id, principal.user_id, title, now, now),
            ).fetchone()
        return _session(row)

    def get_session(self, principal: Principal, session_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM prod_sessions WHERE session_id = %s AND tenant_id = %s AND owner_id = %s AND status != 'deleted'",
                (session_id, principal.tenant_id, principal.user_id),
            ).fetchone()
        return _session(row) if row else None

    def list_sessions(self, principal: Principal) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM prod_sessions WHERE tenant_id = %s AND owner_id = %s AND status != 'deleted' ORDER BY updated_at DESC",
                (principal.tenant_id, principal.user_id),
            ).fetchall()
        return [_session(row) for row in rows]

    def enqueue_job(
        self,
        principal: Principal,
        *,
        session_id: str,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        max_attempts: int,
    ) -> tuple[dict[str, Any], bool]:
        payload_json = _canonical(payload)
        if len(payload_json.encode("utf-8")) > 65536:
            raise QueueConflict("payload_too_large")
        now_epoch = self._clock()
        payload_hash = _hash(payload_json)
        with self._transaction() as connection:
            session = connection.execute(
                "SELECT session_id FROM prod_sessions WHERE session_id = %s AND tenant_id = %s AND owner_id = %s AND status = 'active' FOR UPDATE",
                (session_id, principal.tenant_id, principal.user_id),
            ).fetchone()
            if not session:
                raise KeyError("session_not_found")
            existing = connection.execute(
                "SELECT * FROM prod_jobs WHERE tenant_id = %s AND owner_id = %s AND idempotency_key = %s FOR UPDATE",
                (principal.tenant_id, principal.user_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["payload_sha256"] != payload_hash or existing["kind"] != kind:
                    raise QueueConflict("idempotency_payload_mismatch")
                return _job(existing), False
            job_id = f"job_{uuid4().hex}"
            run_id = f"run_{uuid4().hex}"
            row = connection.execute(
                "INSERT INTO prod_jobs(job_id, run_id, tenant_id, owner_id, session_id, kind, state, payload_json, payload_sha256, idempotency_key, attempt_count, max_attempts, available_at, cancel_requested, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s::jsonb, %s, %s, 0, %s, %s, FALSE, %s, %s) RETURNING *",
                (job_id, run_id, principal.tenant_id, principal.user_id, session_id, kind, payload_json,
                 payload_hash, idempotency_key, max_attempts, now_epoch, _iso(now_epoch), _iso(now_epoch)),
            ).fetchone()
            self._append_job_event(connection, row, "job.queued", {"state": "queued"}, now_epoch)
        return _job(row), True

    def list_jobs(self, principal: Principal) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM prod_jobs WHERE tenant_id = %s AND owner_id = %s ORDER BY created_at DESC",
                (principal.tenant_id, principal.user_id),
            ).fetchall()
        return [_job(row) for row in rows]

    def get_job(self, principal: Principal, job_id: str, *, tenant_worker: bool = False) -> dict[str, Any] | None:
        query = "SELECT * FROM prod_jobs WHERE job_id = %s AND tenant_id = %s"
        values: tuple[object, ...] = (job_id, principal.tenant_id)
        if not tenant_worker:
            query += " AND owner_id = %s"
            values += (principal.user_id,)
        with self._connection() as connection:
            row = connection.execute(query, values).fetchone()
        return _job(row) if row else None

    def claim_next(self, principal: Principal, *, lease_seconds: int) -> dict[str, Any] | None:
        now = self._clock()
        with self._transaction() as connection:
            self._recover_expired(connection, principal.tenant_id, now)
            row = connection.execute(
                "SELECT * FROM prod_jobs WHERE tenant_id = %s AND state = 'queued' AND available_at <= %s "
                "ORDER BY available_at, created_at LIMIT 1 FOR UPDATE SKIP LOCKED",
                (principal.tenant_id, now),
            ).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(32)
            claimed = connection.execute(
                "UPDATE prod_jobs SET state = 'running', attempt_count = attempt_count + 1, lease_hash = %s, lease_expires_at = %s, worker_id = %s, updated_at = %s "
                "WHERE job_id = %s AND state = 'queued' RETURNING *",
                (_hash(token), now + lease_seconds, principal.user_id, _iso(now), row["job_id"]),
            ).fetchone()
            if not claimed:
                raise QueueConflict("job_claim_race")
            self._append_job_event(connection, claimed, "job.claimed", {"state": "running", "attempt_count": claimed["attempt_count"]}, now)
            result = _job(claimed)
            result["lease_token"] = token
            result["payload"] = _as_json(claimed["payload_json"])
            return result

    def heartbeat(self, principal: Principal, *, job_id: str, lease_token: str, lease_seconds: int) -> dict[str, Any]:
        now = self._clock()
        with self._transaction() as connection:
            row = self._require_lease(connection, principal, job_id, lease_token, now)
            updated = connection.execute(
                "UPDATE prod_jobs SET lease_expires_at = %s, updated_at = %s WHERE job_id = %s RETURNING *",
                (now + lease_seconds, _iso(now), job_id),
            ).fetchone()
            self._append_job_event(connection, updated, "job.heartbeat", {"state": "running"}, now)
        return _job(updated)

    def complete(self, principal: Principal, *, job_id: str, lease_token: str, result: dict[str, Any]) -> dict[str, Any]:
        result_json = _canonical(result)
        if len(result_json.encode("utf-8")) > 65536:
            raise QueueConflict("result_too_large")
        now = self._clock()
        with self._transaction() as connection:
            row = self._require_lease(connection, principal, job_id, lease_token, now)
            state = "cancelled" if row["cancel_requested"] else "completed"
            updated = connection.execute(
                "UPDATE prod_jobs SET state = %s, result_json = %s::jsonb, lease_hash = NULL, lease_expires_at = NULL, worker_id = NULL, updated_at = %s, completed_at = %s WHERE job_id = %s RETURNING *",
                (state, result_json, _iso(now), _iso(now), job_id),
            ).fetchone()
            self._insert_outbox(connection, row, state, now)
            self._append_job_event(connection, updated, f"job.{state}", {"state": state, "result_sha256": _hash(result_json)}, now)
        return _job(updated)

    def fail(self, principal: Principal, *, job_id: str, lease_token: str, error_code: str, retry_delay_seconds: int) -> dict[str, Any]:
        now = self._clock()
        with self._transaction() as connection:
            row = self._require_lease(connection, principal, job_id, lease_token, now)
            state = "cancelled" if row["cancel_requested"] else ("dead_letter" if row["attempt_count"] >= row["max_attempts"] else "queued")
            updated = connection.execute(
                "UPDATE prod_jobs SET state = %s, error_code = %s, available_at = %s, lease_hash = NULL, lease_expires_at = NULL, worker_id = NULL, updated_at = %s, completed_at = %s WHERE job_id = %s RETURNING *",
                (state, error_code, now + retry_delay_seconds, _iso(now), _iso(now) if state != "queued" else None, job_id),
            ).fetchone()
            if state != "queued":
                self._insert_outbox(connection, row, state, now)
            event_type = f"job.{state}" if state != "queued" else "job.retry_scheduled"
            self._append_job_event(connection, updated, event_type, {"state": state, "error_code": error_code, "attempt_count": updated["attempt_count"]}, now)
        return _job(updated)

    def cancel(self, principal: Principal, job_id: str) -> dict[str, Any] | None:
        now = self._clock()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM prod_jobs WHERE job_id = %s AND tenant_id = %s AND owner_id = %s FOR UPDATE",
                (job_id, principal.tenant_id, principal.user_id),
            ).fetchone()
            if not row:
                return None
            if row["state"] == "queued":
                updated = connection.execute(
                    "UPDATE prod_jobs SET state = 'cancelled', cancel_requested = TRUE, completed_at = %s, updated_at = %s WHERE job_id = %s RETURNING *",
                    (_iso(now), _iso(now), job_id),
                ).fetchone()
                self._insert_outbox(connection, row, "cancelled", now)
                self._append_job_event(connection, updated, "job.cancelled", {"state": "cancelled"}, now)
            elif row["state"] == "running":
                updated = connection.execute(
                    "UPDATE prod_jobs SET cancel_requested = TRUE, updated_at = %s WHERE job_id = %s RETURNING *",
                    (_iso(now), job_id),
                ).fetchone()
                self._append_job_event(connection, updated, "job.cancel_requested", {"state": "running"}, now)
            else:
                updated = row
        return _job(updated)

    def claim_outbox(self, principal: Principal, *, lease_seconds: int) -> dict[str, Any] | None:
        now = self._clock()
        with self._transaction() as connection:
            connection.execute(
                "UPDATE prod_outbox SET state = 'pending', lease_hash = NULL, lease_expires_at = NULL WHERE tenant_id = %s AND state = 'delivering' AND lease_expires_at <= %s",
                (principal.tenant_id, now),
            )
            row = connection.execute(
                "SELECT * FROM prod_outbox WHERE tenant_id = %s AND state = 'pending' AND available_at <= %s ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED",
                (principal.tenant_id, now),
            ).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(32)
            updated = connection.execute(
                "UPDATE prod_outbox SET state = 'delivering', attempts = attempts + 1, lease_hash = %s, lease_expires_at = %s WHERE event_id = %s RETURNING *",
                (_hash(token), now + lease_seconds, row["event_id"]),
            ).fetchone()
            result = _pg_outbox(updated)
            result["delivery_token"] = token
            return result

    def acknowledge_outbox(self, principal: Principal, *, event_id: str, delivery_token: str) -> dict[str, Any]:
        now = self._clock()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM prod_outbox WHERE event_id = %s AND tenant_id = %s AND state = 'delivering' FOR UPDATE",
                (event_id, principal.tenant_id),
            ).fetchone()
            if not row or not hmac_compare(row["lease_hash"], delivery_token) or float(row["lease_expires_at"] or 0) <= now:
                raise QueueLeaseError("invalid_outbox_lease")
            updated = connection.execute(
                "UPDATE prod_outbox SET state = 'delivered', lease_hash = NULL, lease_expires_at = NULL, delivered_at = %s WHERE event_id = %s RETURNING *",
                (_iso(now), event_id),
            ).fetchone()
        return _pg_outbox(updated)

    def list_job_events(self, principal: Principal, job_id: str) -> list[dict[str, Any]] | None:
        if self.get_job(principal, job_id) is None:
            return None
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM prod_job_events WHERE job_id = %s AND tenant_id = %s AND owner_id = %s ORDER BY seq",
                (job_id, principal.tenant_id, principal.user_id),
            ).fetchall()
        return [_pg_job_event(row) for row in rows]

    def record_export(self, principal: Principal, *, export_id: str, job_id: str, dataset_path: str, dataset_sha256: str, manifest_sha256: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO prod_exports(export_id, tenant_id, owner_id, job_id, dataset_path, dataset_sha256, manifest_sha256, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (export_id, principal.tenant_id, principal.user_id, job_id, dataset_path, dataset_sha256, manifest_sha256, _iso(self._clock())),
            )

    def audit(self, principal: Principal, *, action: str, target_type: str, target_id: str, request_id: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO prod_audit(audit_id, tenant_id, actor_id, action, target_type, target_id_hash, request_id_hash, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (f"aud_{uuid4().hex}", principal.tenant_id, principal.user_id, action, target_type, _hash(target_id), _hash(request_id), _iso(self._clock())),
            )

    def audit_count(self, principal: Principal) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS value FROM prod_audit WHERE tenant_id = %s", (principal.tenant_id,)).fetchone()
        return int(row["value"])

    def revoke_token(self, principal: Principal, *, token_id: str, expires_at: int, reason: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO prod_token_revocations(tenant_id, token_id_hash, expires_at, reason, revoked_by, created_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT(tenant_id, token_id_hash) DO NOTHING",
                (principal.tenant_id, _hash(token_id), expires_at, reason[:80], principal.user_id, _iso(self._clock())),
            )

    def is_token_revoked(self, tenant_id: str, token_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM prod_token_revocations WHERE tenant_id = %s AND token_id_hash = %s AND expires_at > %s",
                (tenant_id, _hash(token_id), int(self._clock())),
            ).fetchone()
        return row is not None

    def put_state(self, principal: Principal, *, namespace: str, record_id: str, value: dict[str, Any], expected_version: int | None = None) -> dict[str, Any]:
        _validate_state_identity(namespace, record_id)
        value_json = _canonical(value)
        if len(value_json.encode("utf-8")) > 262144:
            raise QueueConflict("state_value_too_large")
        now = _iso(self._clock())
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM prod_state_records WHERE tenant_id = %s AND owner_id = %s AND namespace = %s AND record_id = %s FOR UPDATE",
                (principal.tenant_id, principal.user_id, namespace, record_id),
            ).fetchone()
            current = int(row["version"]) if row else 0
            if expected_version is not None and current != expected_version:
                raise QueueConflict("state_version_conflict")
            if row:
                updated = connection.execute(
                    "UPDATE prod_state_records SET version = %s, value_json = %s::jsonb, value_sha256 = %s, updated_at = %s, deleted_at = NULL WHERE tenant_id = %s AND owner_id = %s AND namespace = %s AND record_id = %s RETURNING *",
                    (current + 1, value_json, _hash(value_json), now, principal.tenant_id, principal.user_id, namespace, record_id),
                ).fetchone()
            else:
                updated = connection.execute(
                    "INSERT INTO prod_state_records(tenant_id, owner_id, namespace, record_id, version, value_json, value_sha256, created_at, updated_at) VALUES (%s, %s, %s, %s, 1, %s::jsonb, %s, %s, %s) RETURNING *",
                    (principal.tenant_id, principal.user_id, namespace, record_id, value_json, _hash(value_json), now, now),
                ).fetchone()
        return _pg_state_record(updated)

    def get_state(self, principal: Principal, *, namespace: str, record_id: str) -> dict[str, Any] | None:
        _validate_state_identity(namespace, record_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM prod_state_records WHERE tenant_id = %s AND owner_id = %s AND namespace = %s AND record_id = %s AND deleted_at IS NULL",
                (principal.tenant_id, principal.user_id, namespace, record_id),
            ).fetchone()
        return _pg_state_record(row) if row else None

    def delete_state(self, principal: Principal, *, namespace: str, record_id: str, expected_version: int) -> bool:
        _validate_state_identity(namespace, record_id)
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE prod_state_records SET deleted_at = %s, updated_at = %s, value_json = '{}'::jsonb, value_sha256 = %s WHERE tenant_id = %s AND owner_id = %s AND namespace = %s AND record_id = %s AND version = %s AND deleted_at IS NULL",
                (_iso(self._clock()), _iso(self._clock()), _hash("{}"), principal.tenant_id, principal.user_id, namespace, record_id, expected_version),
            ).rowcount
        return changed == 1

    def apply_retention(self, *, before_epoch: float) -> dict[str, int]:
        cutoff = _iso(before_epoch)
        with self._transaction() as connection:
            outbox = connection.execute("DELETE FROM prod_outbox WHERE state = 'delivered' AND delivered_at < %s", (cutoff,)).rowcount
            audits = connection.execute("DELETE FROM prod_audit WHERE created_at < %s", (cutoff,)).rowcount
            jobs = connection.execute("UPDATE prod_jobs SET payload_json = '{}'::jsonb, result_json = NULL WHERE state IN ('completed','failed','cancelled','dead_letter') AND completed_at < %s", (cutoff,)).rowcount
        return {"outbox_rows_deleted": outbox, "audit_rows_deleted": audits, "terminal_job_payloads_redacted": jobs}

    def _recover_expired(self, connection, tenant_id: str, now: float) -> None:
        rows = connection.execute(
            "SELECT * FROM prod_jobs WHERE tenant_id = %s AND state = 'running' AND lease_expires_at <= %s FOR UPDATE SKIP LOCKED",
            (tenant_id, now),
        ).fetchall()
        for row in rows:
            state = "cancelled" if row["cancel_requested"] else ("dead_letter" if row["attempt_count"] >= row["max_attempts"] else "queued")
            updated = connection.execute(
                "UPDATE prod_jobs SET state = %s, lease_hash = NULL, lease_expires_at = NULL, worker_id = NULL, updated_at = %s, completed_at = %s WHERE job_id = %s AND state = 'running' RETURNING *",
                (state, _iso(now), _iso(now) if state != "queued" else None, row["job_id"]),
            ).fetchone()
            if state != "queued":
                self._insert_outbox(connection, row, state, now)
            self._append_job_event(connection, updated, f"job.{state}" if state != "queued" else "job.lease_recovered", {"state": state, "attempt_count": updated["attempt_count"]}, now)

    def _require_lease(self, connection, principal: Principal, job_id: str, token: str, now: float):
        row = connection.execute(
            "SELECT * FROM prod_jobs WHERE job_id = %s AND tenant_id = %s AND state = 'running' FOR UPDATE",
            (job_id, principal.tenant_id),
        ).fetchone()
        if not row or not hmac_compare(row["lease_hash"], token) or float(row["lease_expires_at"] or 0) <= now:
            raise QueueLeaseError("invalid_or_expired_job_lease")
        return row

    @staticmethod
    def _insert_outbox(connection, job, state: str, now: float) -> None:
        payload = _canonical({"job_id": job["job_id"], "run_id": job["run_id"], "state": state})
        connection.execute(
            "INSERT INTO prod_outbox(event_id, tenant_id, owner_id, job_id, event_type, payload_json, state, attempts, available_at, created_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'pending', 0, %s, %s) ON CONFLICT(event_id) DO NOTHING",
            (f"out_{job['job_id']}_{state}", job["tenant_id"], job["owner_id"], job["job_id"], f"job.{state}", payload, now, _iso(now)),
        )

    @staticmethod
    def _append_job_event(connection, job, event_type: str, payload: dict[str, Any], now: float) -> None:
        sequence = connection.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS value FROM prod_job_events WHERE job_id = %s", (job["job_id"],)).fetchone()["value"]
        connection.execute(
            "INSERT INTO prod_job_events(event_id, job_id, run_id, tenant_id, owner_id, seq, event_type, payload_json, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
            (f"pevt_{uuid4().hex}", job["job_id"], job["run_id"], job["tenant_id"], job["owner_id"], sequence, event_type, _canonical(payload), _iso(now)),
        )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        connection = self._connect_factory()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self._connection() as connection:
            try:
                with connection.transaction():
                    yield connection
            except Exception:
                raise


def _as_json(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else json.loads(value)


def _pg_outbox(row: Any) -> dict[str, Any]:
    normalized = dict(row)
    if isinstance(normalized.get("payload_json"), dict):
        normalized["payload_json"] = _canonical(normalized["payload_json"])
    return _outbox(normalized)


def _pg_job_event(row: Any) -> dict[str, Any]:
    normalized = dict(row)
    if isinstance(normalized.get("payload_json"), dict):
        normalized["payload_json"] = _canonical(normalized["payload_json"])
    return _job_event(normalized)


def _pg_state_record(row: Any) -> dict[str, Any]:
    normalized = dict(row)
    if isinstance(normalized.get("value_json"), dict):
        normalized["value_json"] = _canonical(normalized["value_json"])
    return _state_record(normalized, include_value=True)


_POSTGRES_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (
        "CREATE TABLE prod_sessions (session_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)",
        "CREATE INDEX idx_prod_sessions_owner ON prod_sessions(tenant_id, owner_id, updated_at)",
        "CREATE TABLE prod_jobs (job_id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, session_id TEXT NOT NULL REFERENCES prod_sessions(session_id), kind TEXT NOT NULL, state TEXT NOT NULL, payload_json JSONB NOT NULL, payload_sha256 TEXT NOT NULL, idempotency_key TEXT NOT NULL, attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL, available_at DOUBLE PRECISION NOT NULL, lease_hash TEXT, lease_expires_at DOUBLE PRECISION, worker_id TEXT, cancel_requested BOOLEAN NOT NULL, result_json JSONB, error_code TEXT, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ, UNIQUE(tenant_id, owner_id, idempotency_key))",
        "CREATE INDEX idx_prod_jobs_queue ON prod_jobs(tenant_id, state, available_at, created_at)",
        "CREATE INDEX idx_prod_jobs_owner ON prod_jobs(tenant_id, owner_id, created_at)",
        "CREATE TABLE prod_outbox (event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES prod_jobs(job_id), event_type TEXT NOT NULL, payload_json JSONB NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL, available_at DOUBLE PRECISION NOT NULL, lease_hash TEXT, lease_expires_at DOUBLE PRECISION, created_at TIMESTAMPTZ NOT NULL, delivered_at TIMESTAMPTZ)",
        "CREATE INDEX idx_prod_outbox_delivery ON prod_outbox(tenant_id, state, available_at, created_at)",
        "CREATE TABLE prod_audit (audit_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL, target_id_hash TEXT NOT NULL, request_id_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)",
    )),
    (2, (
        "CREATE TABLE prod_exports (export_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES prod_jobs(job_id), dataset_path TEXT NOT NULL, dataset_sha256 TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)",
        "CREATE TABLE prod_job_events (event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES prod_jobs(job_id), run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, seq INTEGER NOT NULL, event_type TEXT NOT NULL, payload_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL, UNIQUE(job_id, seq))",
        "CREATE INDEX idx_prod_job_events_owner ON prod_job_events(tenant_id, owner_id, job_id, seq)",
    )),
    (3, (
        "CREATE TABLE prod_token_revocations (tenant_id TEXT NOT NULL, token_id_hash TEXT NOT NULL, expires_at BIGINT NOT NULL, reason TEXT NOT NULL, revoked_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(tenant_id, token_id_hash))",
        "CREATE INDEX idx_prod_token_revocations_expiry ON prod_token_revocations(expires_at)",
        "CREATE TABLE prod_state_records (tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, namespace TEXT NOT NULL, record_id TEXT NOT NULL, version INTEGER NOT NULL, value_json JSONB NOT NULL, value_sha256 TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ, PRIMARY KEY(tenant_id, owner_id, namespace, record_id))",
        "CREATE INDEX idx_prod_state_owner ON prod_state_records(tenant_id, owner_id, namespace, updated_at)",
    )),
)
