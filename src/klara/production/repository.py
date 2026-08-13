"""SQLite migrations, tenant partitions, lease queue, and transactional outbox."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
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

    def assert_schema_compatible(self) -> None:
        """Apply the forward-only rollback policy and reject unknown future schema."""

        versions = self.migration_versions()
        expected = tuple(version for version, _ in _MIGRATIONS)
        if versions != expected:
            raise RuntimeError(
                f"production schema is not at the supported forward-only version: {versions}"
            )

    def integrity_report(self) -> dict[str, Any]:
        """Return SQLite integrity, foreign-key, migration, and row-count evidence."""

        with self._connect() as connection:
            quick = [str(row[0]) for row in connection.execute("PRAGMA quick_check").fetchall()]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            counts = {
                table: int(
                    connection.execute(f"SELECT COUNT(*) AS value FROM {table}").fetchone()["value"]
                )
                for table in _PRODUCTION_TABLES
            }
        return {
            "schema_version": "klara.production-integrity.v1",
            "database_kind": "sqlite",
            "quick_check": quick,
            "foreign_key_violation_count": len(foreign_keys),
            "migration_versions": list(self.migration_versions()),
            "row_counts": counts,
            "passed": quick == ["ok"] and not foreign_keys,
        }

    def backup_to(self, destination: str | Path) -> dict[str, Any]:
        """Create and verify a consistent SQLite backup without copying WAL files."""

        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target == self.path.resolve():
            raise ValueError("backup_destination_must_differ")
        staging = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            source = sqlite3.connect(self.path)
            sink = sqlite3.connect(staging)
            try:
                source.backup(sink)
                sink.commit()
            finally:
                sink.close()
                source.close()
            check = _sqlite_file_integrity(staging)
            if not check["passed"]:
                raise RuntimeError("backup_integrity_failed")
            os.replace(staging, target)
        finally:
            if staging.exists():
                staging.unlink()
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return {
            "schema_version": "klara.production-backup.v1",
            "database_kind": "sqlite",
            "path": str(target),
            "sha256": digest,
            "size_bytes": target.stat().st_size,
            "integrity": check,
        }

    def restore_from(self, source: str | Path) -> dict[str, Any]:
        """Restore a verified SQLite backup and keep a recoverable pre-restore copy."""

        backup = Path(source).resolve()
        if not backup.is_file() or backup == self.path.resolve():
            raise ValueError("invalid_restore_source")
        check = _sqlite_file_integrity(backup)
        if not check["passed"]:
            raise RuntimeError("restore_source_integrity_failed")
        staging = self.path.with_name(f".{self.path.name}.{uuid4().hex}.restore")
        previous = self.path.with_suffix(self.path.suffix + ".pre-restore")
        shutil.copy2(backup, staging)
        try:
            if self.path.exists():
                shutil.copy2(self.path, previous)
            os.replace(staging, self.path)
            self.migrate()
            self.assert_schema_compatible()
            restored = self.integrity_report()
            if not restored["passed"]:
                raise RuntimeError("restored_database_integrity_failed")
            return {
                "schema_version": "klara.production-restore.v1",
                "database_kind": "sqlite",
                "source_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
                "pre_restore_path": str(previous) if previous.exists() else None,
                "integrity": restored,
            }
        except Exception:
            if previous.exists():
                os.replace(previous, self.path)
            raise
        finally:
            if staging.exists():
                staging.unlink()

    def apply_retention(self, *, before_epoch: float) -> dict[str, int]:
        """Remove old delivery/audit rows and redact terminal payloads by policy."""

        cutoff = _iso(before_epoch)
        with self._transaction() as connection:
            outbox = connection.execute(
                "DELETE FROM prod_outbox WHERE state = 'delivered' AND delivered_at < ?",
                (cutoff,),
            ).rowcount
            audits = connection.execute(
                "DELETE FROM prod_audit WHERE created_at < ?", (cutoff,)
            ).rowcount
            jobs = connection.execute(
                "UPDATE prod_jobs SET payload_json = '{}', result_json = NULL "
                "WHERE state IN ('completed', 'failed', 'cancelled', 'dead_letter') AND completed_at < ?",
                (cutoff,),
            ).rowcount
        return {
            "outbox_rows_deleted": int(outbox),
            "audit_rows_deleted": int(audits),
            "terminal_job_payloads_redacted": int(jobs),
        }

    def revoke_token(
        self,
        principal: Principal,
        *,
        token_id: str,
        expires_at: int,
        reason: str,
    ) -> None:
        """Persist a tenant-bound credential revocation without storing the bearer."""

        if len(token_id) > 128 or not token_id:
            raise ValueError("invalid_token_id")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO prod_token_revocations(tenant_id, token_id_hash, expires_at, reason, revoked_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(tenant_id, token_id_hash) DO NOTHING",
                (principal.tenant_id, _hash(token_id), expires_at, reason[:80], principal.user_id, _iso(self._clock())),
            )
            connection.commit()

    def is_token_revoked(self, tenant_id: str, token_id: str) -> bool:
        """Return whether the exact tenant/token pair is actively revoked."""

        now = int(self._clock())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM prod_token_revocations WHERE tenant_id = ? AND token_id_hash = ? AND expires_at > ?",
                (tenant_id, _hash(token_id), now),
            ).fetchone()
        return row is not None

    def put_state(
        self,
        principal: Principal,
        *,
        namespace: str,
        record_id: str,
        value: dict[str, Any],
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Create or CAS-update one tenant/owner state record."""

        _validate_state_identity(namespace, record_id)
        value_json = _canonical(value)
        if len(value_json.encode("utf-8")) > 262144:
            raise QueueConflict("state_value_too_large")
        now = _iso(self._clock())
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM prod_state_records WHERE tenant_id = ? AND owner_id = ? AND namespace = ? AND record_id = ?",
                (principal.tenant_id, principal.user_id, namespace, record_id),
            ).fetchone()
            current_version = int(row["version"]) if row else 0
            if expected_version is not None and expected_version != current_version:
                raise QueueConflict("state_version_conflict")
            next_version = current_version + 1
            if row:
                connection.execute(
                    "UPDATE prod_state_records SET version = ?, value_json = ?, value_sha256 = ?, updated_at = ?, deleted_at = NULL "
                    "WHERE tenant_id = ? AND owner_id = ? AND namespace = ? AND record_id = ?",
                    (next_version, value_json, _hash(value_json), now, principal.tenant_id, principal.user_id, namespace, record_id),
                )
            else:
                connection.execute(
                    "INSERT INTO prod_state_records(tenant_id, owner_id, namespace, record_id, version, value_json, value_sha256, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (principal.tenant_id, principal.user_id, namespace, record_id, next_version, value_json, _hash(value_json), now, now),
                )
            updated = connection.execute(
                "SELECT * FROM prod_state_records WHERE tenant_id = ? AND owner_id = ? AND namespace = ? AND record_id = ?",
                (principal.tenant_id, principal.user_id, namespace, record_id),
            ).fetchone()
        return _state_record(updated, include_value=True)

    def get_state(
        self,
        principal: Principal,
        *,
        namespace: str,
        record_id: str,
    ) -> dict[str, Any] | None:
        """Return one visible state record; foreign owners remain opaque."""

        _validate_state_identity(namespace, record_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM prod_state_records WHERE tenant_id = ? AND owner_id = ? AND namespace = ? AND record_id = ? AND deleted_at IS NULL",
                (principal.tenant_id, principal.user_id, namespace, record_id),
            ).fetchone()
        return _state_record(row, include_value=True) if row else None

    def delete_state(
        self,
        principal: Principal,
        *,
        namespace: str,
        record_id: str,
        expected_version: int,
    ) -> bool:
        """CAS tombstone an owner-visible record without cross-scope side channels."""

        _validate_state_identity(namespace, record_id)
        now = _iso(self._clock())
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE prod_state_records SET deleted_at = ?, updated_at = ?, value_json = '{}', value_sha256 = ? "
                "WHERE tenant_id = ? AND owner_id = ? AND namespace = ? AND record_id = ? AND version = ? AND deleted_at IS NULL",
                (now, now, _hash("{}"), principal.tenant_id, principal.user_id, namespace, record_id, expected_version),
            ).rowcount
            connection.commit()
        return changed == 1

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


def _state_record(row: sqlite3.Row, *, include_value: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "klara.production-state-record.v1",
        "tenant_id": row["tenant_id"],
        "owner_id": row["owner_id"],
        "namespace": row["namespace"],
        "record_id": row["record_id"],
        "version": row["version"],
        "value_sha256": row["value_sha256"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_value:
        result["value"] = json.loads(row["value_json"])
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_compare(expected_hash: str | None, raw_value: str) -> bool:
    return bool(expected_hash) and secrets.compare_digest(str(expected_hash), _hash(raw_value))


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def _validate_state_identity(namespace: str, record_id: str) -> None:
    allowed_namespaces = {
        "run",
        "event",
        "plan",
        "context_summary",
        "memory",
        "permission",
        "task",
        "schedule",
        "team",
        "mcp_connection",
        "artifact",
    }
    if namespace not in allowed_namespaces:
        raise ValueError("unsupported_state_namespace")
    if not record_id or len(record_id) > 160 or any(char.isspace() for char in record_id):
        raise ValueError("invalid_state_record_id")


def _sqlite_file_integrity(path: Path) -> dict[str, Any]:
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        quick = [str(row[0]) for row in connection.execute("PRAGMA quick_check").fetchall()]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        versions = [int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
    except sqlite3.DatabaseError as exc:
        return {"quick_check": [type(exc).__name__], "foreign_key_violation_count": -1, "migration_versions": [], "passed": False}
    finally:
        if "connection" in locals():
            connection.close()
    expected = [version for version, _ in _MIGRATIONS]
    return {
        "quick_check": quick,
        "foreign_key_violation_count": len(foreign_keys),
        "migration_versions": versions,
        "passed": quick == ["ok"] and not foreign_keys and versions == expected,
    }


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
    (4, (
        "CREATE TABLE prod_token_revocations (tenant_id TEXT NOT NULL, token_id_hash TEXT NOT NULL, expires_at INTEGER NOT NULL, reason TEXT NOT NULL, revoked_by TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(tenant_id, token_id_hash))",
        "CREATE INDEX idx_prod_token_revocations_expiry ON prod_token_revocations(expires_at)",
        "CREATE TABLE prod_state_records (tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, namespace TEXT NOT NULL, record_id TEXT NOT NULL, version INTEGER NOT NULL, value_json TEXT NOT NULL, value_sha256 TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT, PRIMARY KEY(tenant_id, owner_id, namespace, record_id))",
        "CREATE INDEX idx_prod_state_owner ON prod_state_records(tenant_id, owner_id, namespace, updated_at)",
    )),
)


_PRODUCTION_TABLES = (
    "prod_sessions",
    "prod_jobs",
    "prod_outbox",
    "prod_audit",
    "prod_exports",
    "prod_job_events",
    "prod_token_revocations",
    "prod_state_records",
)
