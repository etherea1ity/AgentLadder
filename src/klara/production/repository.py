"""SQLite migrations, tenant partitions, lease queue, and transactional outbox."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from typing import Any, Iterator
from uuid import uuid4

from klara.production.auth import Principal


SCHEMA_VERSION = "klara.production-store.v1"
_TERMINAL = {"completed", "failed", "cancelled", "dead_letter"}


class QueueConflict(ValueError):
    """Raised for an idempotency collision or invalid state transition."""


class QueueLeaseError(ValueError):
    """Raised when a worker lease is absent, forged, stale, or expired."""


class ProductionRepository:
    """Production-shaped local persistence with explicit schema migrations."""

    def __init__(self, path: str | Path, *, clock=time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._migration_lock = threading.Lock()
        self.migrate()

    def migrate(self) -> None:
        """Apply immutable migrations and verify already-applied checksums."""

        with self._migration_lock, self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            connection.commit()
            for version, statements in _MIGRATIONS:
                checksum = hashlib.sha256("\n".join(statements).encode("utf-8")).hexdigest()
                existing = connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone()
                if existing:
                    if existing["checksum"] != checksum:
                        raise RuntimeError(f"migration checksum mismatch for version {version}")
                    continue
                connection.execute("BEGIN IMMEDIATE")
                try:
                    for statement in statements:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
                        (version, checksum, _iso(self._clock())),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def migration_versions(self) -> tuple[int, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        return tuple(int(row["version"]) for row in rows)

    def create_session(self, principal: Principal, *, title: str) -> dict[str, Any]:
        session_id = f"psess_{uuid4().hex}"
        now = _iso(self._clock())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO prod_sessions(session_id, tenant_id, owner_id, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?)",
                (session_id, principal.tenant_id, principal.user_id, title, now, now),
            )
            connection.commit()
        return self.get_session(principal, session_id) or {}

    def get_session(self, principal: Principal, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM prod_sessions WHERE session_id = ? AND tenant_id = ? AND owner_id = ? AND status != 'deleted'",
                (session_id, principal.tenant_id, principal.user_id),
            ).fetchone()
        return _session(row) if row else None

    def list_sessions(self, principal: Principal) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM prod_sessions WHERE tenant_id = ? AND owner_id = ? AND status != 'deleted' ORDER BY updated_at DESC",
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
        payload_hash = _hash(payload_json)
        now_epoch = self._clock()
        now = _iso(now_epoch)
        with self._transaction() as connection:
            session = connection.execute(
                "SELECT session_id FROM prod_sessions WHERE session_id = ? AND tenant_id = ? AND owner_id = ? AND status = 'active'",
                (session_id, principal.tenant_id, principal.user_id),
            ).fetchone()
            if not session:
                raise KeyError("session_not_found")
            existing = connection.execute(
                "SELECT * FROM prod_jobs WHERE tenant_id = ? AND owner_id = ? AND idempotency_key = ?",
                (principal.tenant_id, principal.user_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["payload_sha256"] != payload_hash or existing["kind"] != kind:
                    raise QueueConflict("idempotency_payload_mismatch")
                return _job(existing), False
            job_id = f"job_{uuid4().hex}"
            run_id = f"run_{uuid4().hex}"
            connection.execute(
                "INSERT INTO prod_jobs(job_id, run_id, tenant_id, owner_id, session_id, kind, state, payload_json, "
                "payload_sha256, idempotency_key, attempt_count, max_attempts, available_at, cancel_requested, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, 0, ?, ?, 0, ?, ?)",
                (job_id, run_id, principal.tenant_id, principal.user_id, session_id, kind, payload_json,
                 payload_hash, idempotency_key, max_attempts, now_epoch, now, now),
            )
            row = connection.execute("SELECT * FROM prod_jobs WHERE job_id = ?", (job_id,)).fetchone()
            self._append_job_event(connection, row, "job.queued", {"state": "queued"}, now_epoch)
        return _job(row), True

    def list_jobs(self, principal: Principal) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM prod_jobs WHERE tenant_id = ? AND owner_id = ? ORDER BY created_at DESC",
                (principal.tenant_id, principal.user_id),
            ).fetchall()
        return [_job(row) for row in rows]

    def get_job(self, principal: Principal, job_id: str, *, tenant_worker: bool = False) -> dict[str, Any] | None:
        query = "SELECT * FROM prod_jobs WHERE job_id = ? AND tenant_id = ?"
        values: tuple[object, ...] = (job_id, principal.tenant_id)
        if not tenant_worker:
            query += " AND owner_id = ?"
            values += (principal.user_id,)
        with self._connect() as connection:
            row = connection.execute(query, values).fetchone()
        return _job(row) if row else None

    def claim_next(self, principal: Principal, *, lease_seconds: int) -> dict[str, Any] | None:
        now = self._clock()
        with self._transaction() as connection:
            self._recover_expired(connection, principal.tenant_id, now)
            row = connection.execute(
                "SELECT * FROM prod_jobs WHERE tenant_id = ? AND state = 'queued' AND available_at <= ? "
                "ORDER BY available_at, created_at LIMIT 1",
                (principal.tenant_id, now),
            ).fetchone()
            if not row:
                return None
            raw_lease = secrets.token_urlsafe(32)
            changed = connection.execute(
                "UPDATE prod_jobs SET state = 'running', attempt_count = attempt_count + 1, lease_hash = ?, "
                "lease_expires_at = ?, worker_id = ?, updated_at = ? WHERE job_id = ? AND state = 'queued'",
                (_hash(raw_lease), now + lease_seconds, principal.user_id, _iso(now), row["job_id"]),
            ).rowcount
            if changed != 1:
                raise QueueConflict("job_claim_race")
            claimed = connection.execute("SELECT * FROM prod_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
            self._append_job_event(
                connection,
                claimed,
                "job.claimed",
                {"state": "running", "attempt_count": int(claimed["attempt_count"])},
                now,
            )
            result = _job(claimed)
            result["lease_token"] = raw_lease
            result["payload"] = json.loads(claimed["payload_json"])
            return result

    def heartbeat(self, principal: Principal, *, job_id: str, lease_token: str, lease_seconds: int) -> dict[str, Any]:
        now = self._clock()
        with self._transaction() as connection:
            row = self._require_lease(connection, principal, job_id, lease_token, now)
            connection.execute(
                "UPDATE prod_jobs SET lease_expires_at = ?, updated_at = ? WHERE job_id = ?",
                (now + lease_seconds, _iso(now), job_id),
            )
            updated = connection.execute("SELECT * FROM prod_jobs WHERE job_id = ?", (job_id,)).fetchone()
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
            connection.execute(
                "UPDATE prod_jobs SET state = ?, result_json = ?, lease_hash = NULL, lease_expires_at = NULL, "
                "worker_id = NULL, updated_at = ?, completed_at = ? WHERE job_id = ?",
                (state, result_json, _iso(now), _iso(now), job_id),
            )
            self._insert_outbox(connection, row, state, now)
            updated = connection.execute("SELECT * FROM prod_jobs WHERE job_id = ?", (job_id,)).fetchone()
            self._append_job_event(
                connection,
                updated,
                f"job.{state}",
                {"state": state, "result_sha256": _hash(result_json)},
                now,
            )
        return _job(updated)

    def fail(
        self,
        principal: Principal,
        *,
        job_id: str,
        lease_token: str,
        error_code: str,
        retry_delay_seconds: int,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._transaction() as connection:
            row = self._require_lease(connection, principal, job_id, lease_token, now)
            if row["cancel_requested"]:
                state = "cancelled"
            elif int(row["attempt_count"]) >= int(row["max_attempts"]):
                state = "dead_letter"
            else:
                state = "queued"
            connection.execute(
                "UPDATE prod_jobs SET state = ?, error_code = ?, available_at = ?, lease_hash = NULL, "
                "lease_expires_at = NULL, worker_id = NULL, updated_at = ?, completed_at = ? WHERE job_id = ?",
                (state, error_code, now + retry_delay_seconds, _iso(now), _iso(now) if state in _TERMINAL else None, job_id),
            )
            if state in _TERMINAL:
                self._insert_outbox(connection, row, state, now)
            updated = connection.execute("SELECT * FROM prod_jobs WHERE job_id = ?", (job_id,)).fetchone()
            self._append_job_event(
                connection,
                updated,
                f"job.{state}" if state in _TERMINAL else "job.retry_scheduled",
                {"state": state, "error_code": error_code, "attempt_count": int(updated["attempt_count"])},
                now,
            )
        return _job(updated)

    def cancel(self, principal: Principal, job_id: str) -> dict[str, Any] | None:
        now = self._clock()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM prod_jobs WHERE job_id = ? AND tenant_id = ? AND owner_id = ?",
                (job_id, principal.tenant_id, principal.user_id),
            ).fetchone()
            if not row:
                return None
            if row["state"] == "queued":
                connection.execute(
                    "UPDATE prod_jobs SET state = 'cancelled', cancel_requested = 1, completed_at = ?, updated_at = ? WHERE job_id = ?",
                    (_iso(now), _iso(now), job_id),
                )
                self._insert_outbox(connection, row, "cancelled", now)
                terminal = connection.execute("SELECT * FROM prod_jobs WHERE job_id = ?", (job_id,)).fetchone()
                self._append_job_event(connection, terminal, "job.cancelled", {"state": "cancelled"}, now)
            elif row["state"] == "running":
                connection.execute(
                    "UPDATE prod_jobs SET cancel_requested = 1, updated_at = ? WHERE job_id = ?",
                    (_iso(now), job_id),
                )
                requested = connection.execute("SELECT * FROM prod_jobs WHERE job_id = ?", (job_id,)).fetchone()
                self._append_job_event(connection, requested, "job.cancel_requested", {"state": "running"}, now)
            updated = connection.execute("SELECT * FROM prod_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _job(updated)

    def claim_outbox(self, principal: Principal, *, lease_seconds: int) -> dict[str, Any] | None:
        now = self._clock()
        with self._transaction() as connection:
            connection.execute(
                "UPDATE prod_outbox SET state = 'pending', lease_hash = NULL, lease_expires_at = NULL "
                "WHERE tenant_id = ? AND state = 'delivering' AND lease_expires_at <= ?",
                (principal.tenant_id, now),
            )
            row = connection.execute(
                "SELECT * FROM prod_outbox WHERE tenant_id = ? AND state = 'pending' AND available_at <= ? ORDER BY created_at LIMIT 1",
                (principal.tenant_id, now),
            ).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(32)
            connection.execute(
                "UPDATE prod_outbox SET state = 'delivering', attempts = attempts + 1, lease_hash = ?, lease_expires_at = ? WHERE event_id = ?",
                (_hash(token), now + lease_seconds, row["event_id"]),
            )
            updated = connection.execute("SELECT * FROM prod_outbox WHERE event_id = ?", (row["event_id"],)).fetchone()
            result = _outbox(updated)
            result["delivery_token"] = token
            return result

    def acknowledge_outbox(self, principal: Principal, *, event_id: str, delivery_token: str) -> dict[str, Any]:
        now = self._clock()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM prod_outbox WHERE event_id = ? AND tenant_id = ? AND state = 'delivering'",
                (event_id, principal.tenant_id),
            ).fetchone()
            if not row or not hmac_compare(row["lease_hash"], delivery_token) or float(row["lease_expires_at"] or 0) <= now:
                raise QueueLeaseError("invalid_outbox_lease")
            connection.execute(
                "UPDATE prod_outbox SET state = 'delivered', lease_hash = NULL, lease_expires_at = NULL, delivered_at = ? WHERE event_id = ?",
                (_iso(now), event_id),
            )
            updated = connection.execute("SELECT * FROM prod_outbox WHERE event_id = ?", (event_id,)).fetchone()
        return _outbox(updated)

    def record_export(
        self,
        principal: Principal,
        *,
        export_id: str,
        job_id: str,
        dataset_path: str,
        dataset_sha256: str,
        manifest_sha256: str,
    ) -> None:
        now = _iso(self._clock())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO prod_exports(export_id, tenant_id, owner_id, job_id, dataset_path, dataset_sha256, manifest_sha256, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (export_id, principal.tenant_id, principal.user_id, job_id, dataset_path, dataset_sha256, manifest_sha256, now),
            )
            connection.commit()

    def list_job_events(self, principal: Principal, job_id: str) -> list[dict[str, Any]] | None:
        """List public queue events only when the owner can see the job."""

        if self.get_job(principal, job_id) is None:
            return None
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM prod_job_events WHERE job_id = ? AND tenant_id = ? AND owner_id = ? ORDER BY seq",
                (job_id, principal.tenant_id, principal.user_id),
            ).fetchall()
        return [_job_event(row) for row in rows]

    def audit(self, principal: Principal, *, action: str, target_type: str, target_id: str, request_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO prod_audit(audit_id, tenant_id, actor_id, action, target_type, target_id_hash, request_id_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"aud_{uuid4().hex}", principal.tenant_id, principal.user_id, action, target_type,
                 _hash(target_id), _hash(request_id), _iso(self._clock())),
            )
            connection.commit()

    def audit_count(self, principal: Principal) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS value FROM prod_audit WHERE tenant_id = ?",
                (principal.tenant_id,),
            ).fetchone()
        return int(row["value"])

    def _recover_expired(self, connection: sqlite3.Connection, tenant_id: str, now: float) -> None:
        rows = connection.execute(
            "SELECT * FROM prod_jobs WHERE tenant_id = ? AND state = 'running' AND lease_expires_at <= ?",
            (tenant_id, now),
        ).fetchall()
        for row in rows:
            state = "cancelled" if row["cancel_requested"] else (
                "dead_letter" if int(row["attempt_count"]) >= int(row["max_attempts"]) else "queued"
            )
            connection.execute(
                "UPDATE prod_jobs SET state = ?, lease_hash = NULL, lease_expires_at = NULL, worker_id = NULL, "
                "updated_at = ?, completed_at = ? WHERE job_id = ? AND state = 'running'",
                (state, _iso(now), _iso(now) if state in _TERMINAL else None, row["job_id"]),
            )
            if state in _TERMINAL:
                self._insert_outbox(connection, row, state, now)
            updated = connection.execute("SELECT * FROM prod_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
            self._append_job_event(
                connection,
                updated,
                f"job.{state}" if state in _TERMINAL else "job.lease_recovered",
                {"state": state, "attempt_count": int(updated["attempt_count"])},
                now,
            )

    def _require_lease(
        self,
        connection: sqlite3.Connection,
        principal: Principal,
        job_id: str,
        token: str,
        now: float,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM prod_jobs WHERE job_id = ? AND tenant_id = ? AND state = 'running'",
            (job_id, principal.tenant_id),
        ).fetchone()
        if not row or not hmac_compare(row["lease_hash"], token) or float(row["lease_expires_at"] or 0) <= now:
            raise QueueLeaseError("invalid_or_expired_job_lease")
        return row

    @staticmethod
    def _insert_outbox(connection: sqlite3.Connection, job: sqlite3.Row, state: str, now: float) -> None:
        payload = _canonical({"job_id": job["job_id"], "run_id": job["run_id"], "state": state})
        connection.execute(
            "INSERT OR IGNORE INTO prod_outbox(event_id, tenant_id, owner_id, job_id, event_type, payload_json, "
            "state, attempts, available_at, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
            (f"out_{job['job_id']}_{state}", job["tenant_id"], job["owner_id"], job["job_id"],
             f"job.{state}", payload, now, _iso(now)),
        )

    @staticmethod
    def _append_job_event(
        connection: sqlite3.Connection,
        job: sqlite3.Row,
        event_type: str,
        payload: dict[str, Any],
        now: float,
    ) -> None:
        next_sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS value FROM prod_job_events WHERE job_id = ?",
                (job["job_id"],),
            ).fetchone()["value"]
        )
        connection.execute(
            "INSERT INTO prod_job_events(event_id, job_id, run_id, tenant_id, owner_id, seq, event_type, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"pevt_{uuid4().hex}", job["job_id"], job["run_id"], job["tenant_id"], job["owner_id"],
             next_sequence, event_type, _canonical(payload), _iso(now)),
        )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()


def _session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "klara.production-session.v1",
        "session_id": row["session_id"],
        "tenant_id": row["tenant_id"],
        "owner_id": row["owner_id"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _job(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "klara.production-job.v1",
        "job_id": row["job_id"],
        "run_id": row["run_id"],
        "tenant_id": row["tenant_id"],
        "owner_id": row["owner_id"],
        "session_id": row["session_id"],
        "kind": row["kind"],
        "state": row["state"],
        "payload_sha256": row["payload_sha256"],
        "attempt_count": row["attempt_count"],
        "max_attempts": row["max_attempts"],
        "cancel_requested": bool(row["cancel_requested"]),
        "error_code": row["error_code"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def _outbox(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "klara.production-outbox.v1",
        "event_id": row["event_id"],
        "tenant_id": row["tenant_id"],
        "owner_id": row["owner_id"],
        "job_id": row["job_id"],
        "event_type": row["event_type"],
        "payload": json.loads(row["payload_json"]),
        "state": row["state"],
        "attempts": row["attempts"],
        "created_at": row["created_at"],
        "delivered_at": row["delivered_at"],
    }


def _job_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "klara.production-job-event.v1",
        "event_id": row["event_id"],
        "job_id": row["job_id"],
        "run_id": row["run_id"],
        "seq": row["seq"],
        "event_type": row["event_type"],
        "payload": json.loads(row["payload_json"]),
        "created_at": row["created_at"],
    }


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_compare(expected_hash: str | None, raw_value: str) -> bool:
    return bool(expected_hash) and secrets.compare_digest(str(expected_hash), _hash(raw_value))


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (
        "CREATE TABLE prod_sessions (session_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE INDEX idx_prod_sessions_owner ON prod_sessions(tenant_id, owner_id, updated_at)",
        "CREATE TABLE prod_jobs (job_id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, session_id TEXT NOT NULL REFERENCES prod_sessions(session_id), kind TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, idempotency_key TEXT NOT NULL, attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL, available_at REAL NOT NULL, lease_hash TEXT, lease_expires_at REAL, worker_id TEXT, cancel_requested INTEGER NOT NULL, result_json TEXT, error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT, UNIQUE(tenant_id, owner_id, idempotency_key))",
        "CREATE INDEX idx_prod_jobs_queue ON prod_jobs(tenant_id, state, available_at, created_at)",
        "CREATE INDEX idx_prod_jobs_owner ON prod_jobs(tenant_id, owner_id, created_at)",
        "CREATE TABLE prod_outbox (event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES prod_jobs(job_id), event_type TEXT NOT NULL, payload_json TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL, available_at REAL NOT NULL, lease_hash TEXT, lease_expires_at REAL, created_at TEXT NOT NULL, delivered_at TEXT)",
        "CREATE INDEX idx_prod_outbox_delivery ON prod_outbox(tenant_id, state, available_at, created_at)",
        "CREATE TABLE prod_audit (audit_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL, target_id_hash TEXT NOT NULL, request_id_hash TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE INDEX idx_prod_audit_tenant ON prod_audit(tenant_id, created_at)",
    )),
    (2, (
        "CREATE TABLE prod_exports (export_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES prod_jobs(job_id), dataset_path TEXT NOT NULL, dataset_sha256 TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE INDEX idx_prod_exports_owner ON prod_exports(tenant_id, owner_id, created_at)",
    )),
    (3, (
        "CREATE TABLE prod_job_events (event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES prod_jobs(job_id), run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, seq INTEGER NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(job_id, seq))",
        "CREATE INDEX idx_prod_job_events_owner ON prod_job_events(tenant_id, owner_id, job_id, seq)",
    )),
)
