"""SQLite durability adapter for Klara long-term memory."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator
from klara.memory.models import (
    CandidateStatus,
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryKind,
    MemoryProvenance,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
)


class SQLiteMemoryRepository:
    """Persist owner-partitioned records, candidates, and content-free audit events."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def save_record(self, record: MemoryRecord) -> None:
        payload = json.dumps(record.to_owner_dict(), ensure_ascii=False, sort_keys=True)
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO memory_records
                   (memory_id, tenant_id, user_id, status, updated_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, user_id, memory_id) DO UPDATE SET
                     tenant_id=excluded.tenant_id,
                     user_id=excluded.user_id,
                     status=excluded.status,
                     updated_at=excluded.updated_at,
                     payload=excluded.payload""",
                (
                    record.memory_id,
                    record.scope.tenant_id,
                    record.scope.user_id,
                    record.status.value,
                    record.updated_at,
                    payload,
                ),
            )

    def get_record(self, scope: MemoryScope, memory_id: str) -> MemoryRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM memory_records WHERE memory_id=? AND tenant_id=? AND user_id=?",
                (memory_id, scope.tenant_id, scope.user_id),
            ).fetchone()
        return _record_from_json(row[0]) if row else None

    def list_records(self, scope: MemoryScope) -> list[MemoryRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM memory_records
                   WHERE tenant_id=? AND user_id=? ORDER BY updated_at DESC, memory_id""",
                (scope.tenant_id, scope.user_id),
            ).fetchall()
        return [_record_from_json(row[0]) for row in rows]

    def hard_delete_record(self, scope: MemoryScope, memory_id: str) -> bool:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM memory_records WHERE memory_id=? AND tenant_id=? AND user_id=?",
                (memory_id, scope.tenant_id, scope.user_id),
            )
        return cursor.rowcount == 1

    def save_candidate(self, candidate: MemoryCandidate) -> None:
        payload = json.dumps(candidate.to_owner_dict(), ensure_ascii=False, sort_keys=True)
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO memory_candidates
                   (candidate_id, tenant_id, user_id, status, created_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, user_id, candidate_id) DO UPDATE SET
                     status=excluded.status, payload=excluded.payload""",
                (
                    candidate.candidate_id,
                    candidate.scope.tenant_id,
                    candidate.scope.user_id,
                    candidate.status.value,
                    candidate.created_at,
                    payload,
                ),
            )

    def get_candidate(self, scope: MemoryScope, candidate_id: str) -> MemoryCandidate | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM memory_candidates WHERE candidate_id=? AND tenant_id=? AND user_id=?",
                (candidate_id, scope.tenant_id, scope.user_id),
            ).fetchone()
        return _candidate_from_json(row[0]) if row else None

    def list_candidates(self, scope: MemoryScope) -> list[MemoryCandidate]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM memory_candidates
                   WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC, candidate_id""",
                (scope.tenant_id, scope.user_id),
            ).fetchall()
        return [_candidate_from_json(row[0]) for row in rows]

    def hard_delete_candidate(self, scope: MemoryScope, candidate_id: str) -> bool:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM memory_candidates WHERE candidate_id=? AND tenant_id=? AND user_id=?",
                (candidate_id, scope.tenant_id, scope.user_id),
            )
        return cursor.rowcount == 1

    def append_audit(self, event: MemoryAuditEvent) -> None:
        payload = json.dumps(event.to_owner_dict(), ensure_ascii=False, sort_keys=True)
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO memory_audit
                   (audit_id, tenant_id, user_id, record_id, occurred_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event.audit_id,
                    event.tenant_id,
                    event.user_id,
                    event.record_id,
                    event.occurred_at,
                    payload,
                ),
            )

    def list_audit(self, scope: MemoryScope) -> list[MemoryAuditEvent]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM memory_audit
                   WHERE tenant_id=? AND user_id=? ORDER BY occurred_at DESC, audit_id""",
                (scope.tenant_id, scope.user_id),
            ).fetchall()
        return [MemoryAuditEvent(**json.loads(row[0])) for row in rows]

    def raw_content_occurrences(self, content: str) -> int:
        """Support deletion proof by scanning durable payload columns."""

        with self._connection() as connection:
            total = 0
            for table in ("memory_records", "memory_candidates", "memory_audit"):
                row = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE instr(payload, ?) > 0",  # noqa: S608
                    (content,),
                ).fetchone()
                total += int(row[0])
        return total

    def close(self) -> None:
        """Repository connections are per operation, so close is intentionally empty."""

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS memory_records (
                  memory_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  PRIMARY KEY(tenant_id, user_id, memory_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_owner
                  ON memory_records(tenant_id, user_id, status, updated_at);
                CREATE TABLE IF NOT EXISTS memory_candidates (
                  candidate_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  PRIMARY KEY(tenant_id, user_id, candidate_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_candidate_owner
                  ON memory_candidates(tenant_id, user_id, status, created_at);
                CREATE TABLE IF NOT EXISTS memory_audit (
                  audit_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  record_id TEXT NOT NULL,
                  occurred_at TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  PRIMARY KEY(tenant_id, user_id, audit_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_audit_owner
                  ON memory_audit(tenant_id, user_id, occurred_at);
                """
            )
            _migrate_owner_primary_keys(connection)
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_owner
                  ON memory_records(tenant_id, user_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_memory_candidate_owner
                  ON memory_candidates(tenant_id, user_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_memory_audit_owner
                  ON memory_audit(tenant_id, user_id, occurred_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Commit or rollback one operation, then always release the file handle."""

        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _scope(value: dict[str, object]) -> MemoryScope:
    return MemoryScope(**value)


def _provenance(value: dict[str, object]) -> MemoryProvenance:
    return MemoryProvenance(**value)


def _record_from_json(payload: str) -> MemoryRecord:
    value = json.loads(payload)
    value["scope"] = _scope(value["scope"])
    value["provenance"] = _provenance(value["provenance"])
    value["kind"] = MemoryKind(value["kind"])
    value["sensitivity"] = MemorySensitivity(value["sensitivity"])
    value["status"] = MemoryStatus(value["status"])
    return MemoryRecord(**value)


def _candidate_from_json(payload: str) -> MemoryCandidate:
    value = json.loads(payload)
    value["scope"] = _scope(value["scope"])
    value["provenance"] = _provenance(value["provenance"])
    value["kind"] = MemoryKind(value["kind"])
    value["sensitivity"] = MemorySensitivity(value["sensitivity"])
    value["status"] = CandidateStatus(value["status"])
    return MemoryCandidate(**value)


def _migrate_owner_primary_keys(connection: sqlite3.Connection) -> None:
    """Upgrade legacy global IDs to owner-scoped composite primary keys."""

    migrations = {
        "memory_records": {
            "id": "memory_id",
            "columns": "memory_id, tenant_id, user_id, status, updated_at, payload",
            "definition": """
                memory_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(tenant_id, user_id, memory_id)
            """,
        },
        "memory_candidates": {
            "id": "candidate_id",
            "columns": "candidate_id, tenant_id, user_id, status, created_at, payload",
            "definition": """
                candidate_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(tenant_id, user_id, candidate_id)
            """,
        },
        "memory_audit": {
            "id": "audit_id",
            "columns": "audit_id, tenant_id, user_id, record_id, occurred_at, payload",
            "definition": """
                audit_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(tenant_id, user_id, audit_id)
            """,
        },
    }
    for table, spec in migrations.items():
        info = connection.execute(f"PRAGMA table_info({table})").fetchall()
        primary_key = [
            row[1]
            for row in sorted(info, key=lambda item: item[5])
            if row[5]
        ]
        expected = ["tenant_id", "user_id", str(spec["id"])]
        if primary_key == expected:
            continue
        temporary = f"{table}_owner_v2"
        connection.execute(f"DROP TABLE IF EXISTS {temporary}")
        connection.execute(f"CREATE TABLE {temporary} ({spec['definition']})")
        connection.execute(
            f"INSERT INTO {temporary} ({spec['columns']}) "
            f"SELECT {spec['columns']} FROM {table}"
        )
        connection.execute(f"DROP TABLE {table}")
        connection.execute(f"ALTER TABLE {temporary} RENAME TO {table}")
