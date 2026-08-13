"""SQLite repository for schedules, occurrences, leases, and notifications."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Iterator

from klara.scheduler.models import (
    MisfirePolicy,
    OccurrenceStatus,
    OverlapPolicy,
    Schedule,
    ScheduleKind,
    ScheduleNotification,
    ScheduleOccurrence,
    SchedulerLease,
    ScheduleStatus,
)
from klara.tasks import TaskScope


class SQLiteScheduleRepository:
    SCHEMA_VERSION = "klara.scheduler.sqlite.v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def create_schedule(self, schedule: Schedule) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO schedules
                   (schedule_id, tenant_id, owner_id, status, next_run_at, updated_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    schedule.schedule_id,
                    schedule.scope.tenant_id,
                    schedule.scope.owner_id,
                    schedule.status.value,
                    schedule.next_run_at,
                    schedule.updated_at,
                    _dump(schedule.to_public_dict()),
                ),
            )

    def save_schedule(self, schedule: Schedule, *, prior_updated_at: str) -> None:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """UPDATE schedules SET status=?, next_run_at=?, updated_at=?, payload=?
                   WHERE schedule_id=? AND tenant_id=? AND owner_id=? AND updated_at=?""",
                (
                    schedule.status.value,
                    schedule.next_run_at,
                    schedule.updated_at,
                    _dump(schedule.to_public_dict()),
                    schedule.schedule_id,
                    schedule.scope.tenant_id,
                    schedule.scope.owner_id,
                    prior_updated_at,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("schedule_changed_concurrently")

    def get_schedule(self, scope: TaskScope, schedule_id: str) -> Schedule | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM schedules
                   WHERE schedule_id=? AND tenant_id=? AND owner_id=?""",
                (schedule_id, scope.tenant_id, scope.owner_id),
            ).fetchone()
        return _schedule(row[0]) if row else None

    def list_schedules(self, scope: TaskScope) -> list[Schedule]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM schedules WHERE tenant_id=? AND owner_id=?
                   ORDER BY updated_at DESC, schedule_id""",
                (scope.tenant_id, scope.owner_id),
            ).fetchall()
        return [_schedule(row[0]) for row in rows]

    def list_due(self, scope: TaskScope, now: str) -> list[Schedule]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM schedules
                   WHERE tenant_id=? AND owner_id=? AND status='active'
                   AND next_run_at IS NOT NULL AND next_run_at<=?
                   ORDER BY next_run_at, schedule_id""",
                (scope.tenant_id, scope.owner_id, now),
            ).fetchall()
        return [_schedule(row[0]) for row in rows]

    def acquire_lease(
        self,
        *,
        scope: TaskScope,
        schedule_id: str,
        worker_id: str,
        now: str,
        expires_at: str,
    ) -> SchedulerLease | None:
        token = secrets.token_urlsafe(32)
        token_hash = _hash(token)
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT expires_at FROM scheduler_leases
                   WHERE schedule_id=? AND tenant_id=? AND owner_id=?""",
                (schedule_id, scope.tenant_id, scope.owner_id),
            ).fetchone()
            if row is not None and row[0] > now:
                return None
            connection.execute(
                """INSERT INTO scheduler_leases
                   (schedule_id, tenant_id, owner_id, worker_id, token_sha256, heartbeat_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(schedule_id, tenant_id, owner_id) DO UPDATE SET
                     worker_id=excluded.worker_id, token_sha256=excluded.token_sha256,
                     heartbeat_at=excluded.heartbeat_at, expires_at=excluded.expires_at""",
                (
                    schedule_id,
                    scope.tenant_id,
                    scope.owner_id,
                    worker_id,
                    token_hash,
                    now,
                    expires_at,
                ),
            )
        return SchedulerLease(schedule_id, worker_id, token, expires_at)

    def heartbeat_lease(
        self,
        *,
        scope: TaskScope,
        lease: SchedulerLease,
        now: str,
        expires_at: str,
    ) -> bool:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """UPDATE scheduler_leases SET heartbeat_at=?, expires_at=?
                   WHERE schedule_id=? AND tenant_id=? AND owner_id=?
                   AND worker_id=? AND token_sha256=? AND expires_at>?""",
                (
                    now,
                    expires_at,
                    lease.schedule_id,
                    scope.tenant_id,
                    scope.owner_id,
                    lease.worker_id,
                    _hash(lease.token),
                    now,
                ),
            )
        return cursor.rowcount == 1

    def release_lease(self, *, scope: TaskScope, lease: SchedulerLease) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """DELETE FROM scheduler_leases
                   WHERE schedule_id=? AND tenant_id=? AND owner_id=?
                   AND worker_id=? AND token_sha256=?""",
                (
                    lease.schedule_id,
                    scope.tenant_id,
                    scope.owner_id,
                    lease.worker_id,
                    _hash(lease.token),
                ),
            )

    def reserve_occurrence(
        self, scope: TaskScope, occurrence: ScheduleOccurrence
    ) -> tuple[ScheduleOccurrence, bool]:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM schedule_occurrences
                   WHERE occurrence_id=? AND tenant_id=? AND owner_id=?""",
                (occurrence.occurrence_id, scope.tenant_id, scope.owner_id),
            ).fetchone()
            if row is not None:
                return _occurrence(row[0]), False
            connection.execute(
                """INSERT INTO schedule_occurrences
                   (occurrence_id, schedule_id, task_id, tenant_id, owner_id, status,
                    scheduled_for, updated_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    occurrence.occurrence_id,
                    occurrence.schedule_id,
                    occurrence.task_id,
                    scope.tenant_id,
                    scope.owner_id,
                    occurrence.status.value,
                    occurrence.scheduled_for,
                    occurrence.updated_at,
                    _dump(occurrence.to_public_dict()),
                ),
            )
        return occurrence, True

    def save_occurrence(self, scope: TaskScope, occurrence: ScheduleOccurrence) -> None:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """UPDATE schedule_occurrences SET status=?, updated_at=?, payload=?
                   WHERE occurrence_id=? AND tenant_id=? AND owner_id=?""",
                (
                    occurrence.status.value,
                    occurrence.updated_at,
                    _dump(occurrence.to_public_dict()),
                    occurrence.occurrence_id,
                    scope.tenant_id,
                    scope.owner_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("schedule_occurrence_not_found")

    def list_occurrences(
        self, scope: TaskScope, schedule_id: str | None = None
    ) -> list[ScheduleOccurrence]:
        query = "SELECT payload FROM schedule_occurrences WHERE tenant_id=? AND owner_id=?"
        parameters: list[str] = [scope.tenant_id, scope.owner_id]
        if schedule_id is not None:
            query += " AND schedule_id=?"
            parameters.append(schedule_id)
        query += " ORDER BY scheduled_for DESC, occurrence_id"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_occurrence(row[0]) for row in rows]

    def list_pending_occurrences(self, scope: TaskScope) -> list[ScheduleOccurrence]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM schedule_occurrences
                   WHERE tenant_id=? AND owner_id=? AND status='reserved'
                   ORDER BY scheduled_for, occurrence_id""",
                (scope.tenant_id, scope.owner_id),
            ).fetchall()
        return [_occurrence(row[0]) for row in rows]

    def save_notification(
        self, scope: TaskScope, notification: ScheduleNotification
    ) -> bool:
        with self._lock, self._connection() as connection:
            try:
                connection.execute(
                    """INSERT INTO schedule_notifications
                       (notification_id, occurrence_id, tenant_id, owner_id,
                        read_at, delivered_at, payload)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        notification.notification_id,
                        notification.occurrence_id,
                        scope.tenant_id,
                        scope.owner_id,
                        notification.read_at,
                        notification.delivered_at,
                        _dump(notification.to_public_dict()),
                    ),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def list_notifications(self, scope: TaskScope) -> list[ScheduleNotification]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM schedule_notifications
                   WHERE tenant_id=? AND owner_id=? ORDER BY rowid DESC""",
                (scope.tenant_id, scope.owner_id),
            ).fetchall()
        return [ScheduleNotification(**json.loads(row[0])) for row in rows]

    def list_pending_notifications(self, scope: TaskScope) -> list[ScheduleNotification]:
        """Return notifications not yet acknowledged by the delivery callback."""

        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM schedule_notifications
                   WHERE tenant_id=? AND owner_id=? AND delivered_at IS NULL
                   ORDER BY rowid""",
                (scope.tenant_id, scope.owner_id),
            ).fetchall()
        return [ScheduleNotification(**json.loads(row[0])) for row in rows]

    def mark_notification_delivered(
        self, scope: TaskScope, notification_id: str, delivered_at: str
    ) -> ScheduleNotification | None:
        """Persist delivery only after the external notifier returns successfully."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM schedule_notifications
                   WHERE notification_id=? AND tenant_id=? AND owner_id=?""",
                (notification_id, scope.tenant_id, scope.owner_id),
            ).fetchone()
            if row is None:
                return None
            notification = replace(
                ScheduleNotification(**json.loads(row[0])), delivered_at=delivered_at
            )
            connection.execute(
                """UPDATE schedule_notifications SET delivered_at=?, payload=?
                   WHERE notification_id=? AND tenant_id=? AND owner_id=?""",
                (
                    delivered_at,
                    _dump(notification.to_public_dict()),
                    notification_id,
                    scope.tenant_id,
                    scope.owner_id,
                ),
            )
        return notification

    def mark_notification_read(
        self, scope: TaskScope, notification_id: str, read_at: str
    ) -> ScheduleNotification | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM schedule_notifications
                   WHERE notification_id=? AND tenant_id=? AND owner_id=?""",
                (notification_id, scope.tenant_id, scope.owner_id),
            ).fetchone()
            if row is None:
                return None
            notification = replace(
                ScheduleNotification(**json.loads(row[0])), read_at=read_at
            )
            connection.execute(
                """UPDATE schedule_notifications SET read_at=?, payload=?
                   WHERE notification_id=? AND tenant_id=? AND owner_id=?""",
                (
                    read_at,
                    _dump(notification.to_public_dict()),
                    notification_id,
                    scope.tenant_id,
                    scope.owner_id,
                ),
            )
        return notification

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS scheduler_schema (
                  version TEXT PRIMARY KEY,
                  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS schedules (
                  schedule_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  next_run_at TEXT,
                  updated_at TEXT NOT NULL,
                  payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_schedule_due
                  ON schedules(tenant_id, owner_id, status, next_run_at);
                CREATE TABLE IF NOT EXISTS scheduler_leases (
                  schedule_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  worker_id TEXT NOT NULL,
                  token_sha256 TEXT NOT NULL,
                  heartbeat_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  PRIMARY KEY(schedule_id, tenant_id, owner_id)
                );
                CREATE TABLE IF NOT EXISTS schedule_occurrences (
                  occurrence_id TEXT PRIMARY KEY,
                  schedule_id TEXT NOT NULL,
                  task_id TEXT,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  scheduled_for TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  FOREIGN KEY(schedule_id) REFERENCES schedules(schedule_id)
                );
                CREATE INDEX IF NOT EXISTS idx_occurrence_owner
                  ON schedule_occurrences(tenant_id, owner_id, status, scheduled_for);
                CREATE TABLE IF NOT EXISTS schedule_notifications (
                  notification_id TEXT PRIMARY KEY,
                  occurrence_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  read_at TEXT,
                  delivered_at TEXT,
                  payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notification_occurrence
                  ON schedule_notifications(tenant_id, owner_id, occurrence_id);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO scheduler_schema(version) VALUES (?)",
                (self.SCHEMA_VERSION,),
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(schedule_notifications)"
                ).fetchall()
            }
            if "delivered_at" not in columns:
                connection.execute(
                    "ALTER TABLE schedule_notifications ADD COLUMN delivered_at TEXT"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _schedule(payload: str) -> Schedule:
    value = json.loads(payload)
    value["scope"] = TaskScope(**value["scope"])
    value["kind"] = ScheduleKind(value["kind"])
    value["status"] = ScheduleStatus(value["status"])
    value["misfire_policy"] = MisfirePolicy(value["misfire_policy"])
    value["overlap_policy"] = OverlapPolicy(value["overlap_policy"])
    value["weekdays"] = tuple(value.get("weekdays", ()))
    return Schedule(**value)


def _occurrence(payload: str) -> ScheduleOccurrence:
    value = json.loads(payload)
    value["status"] = OccurrenceStatus(value["status"])
    return ScheduleOccurrence(**value)
