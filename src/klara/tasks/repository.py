"""SQLite persistence primitives for durable tasks."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from typing import Iterator

from klara.tasks.models import (
    AttemptOutcome,
    DurableTask,
    TaskArtifact,
    TaskAttempt,
    TaskCheckpoint,
    TaskEvent,
    TaskScope,
    TaskState,
)


class TaskWriteConflict(RuntimeError):
    """Raised when another worker changed a task after it was read."""


class SQLiteTaskRepository:
    """Tenant-scoped SQLite task store with compare-and-swap transitions."""

    SCHEMA_VERSION = "klara.durable-tasks.sqlite.v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def create_task(self, task: DurableTask, event: TaskEvent) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO durable_tasks
                   (task_id, tenant_id, owner_id, state, updated_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    task.task_id,
                    task.scope.tenant_id,
                    task.scope.owner_id,
                    task.state.value,
                    task.updated_at,
                    _dump(task.to_owner_dict()),
                ),
            )
            self._insert_event(connection, task.scope, event)

    def get_task(self, scope: TaskScope, task_id: str) -> DurableTask | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM durable_tasks
                   WHERE task_id=? AND tenant_id=? AND owner_id=?""",
                (task_id, scope.tenant_id, scope.owner_id),
            ).fetchone()
        return _task_from_json(row[0]) if row else None

    def list_tasks(self, scope: TaskScope) -> list[DurableTask]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM durable_tasks
                   WHERE tenant_id=? AND owner_id=? ORDER BY updated_at DESC, task_id""",
                (scope.tenant_id, scope.owner_id),
            ).fetchall()
        return [_task_from_json(row[0]) for row in rows]

    def save_transition(
        self,
        *,
        scope: TaskScope,
        prior_updated_at: str,
        task: DurableTask,
        event: TaskEvent,
        new_attempt: TaskAttempt | None = None,
        close_attempt: TaskAttempt | None = None,
        update_attempt: TaskAttempt | None = None,
    ) -> None:
        """Commit task, event, and attempt mutation as one atomic transition."""

        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """UPDATE durable_tasks SET state=?, updated_at=?, payload=?
                   WHERE task_id=? AND tenant_id=? AND owner_id=? AND updated_at=?""",
                (
                    task.state.value,
                    task.updated_at,
                    _dump(task.to_owner_dict()),
                    task.task_id,
                    scope.tenant_id,
                    scope.owner_id,
                    prior_updated_at,
                ),
            )
            if cursor.rowcount != 1:
                raise TaskWriteConflict("task_changed_concurrently")
            if new_attempt is not None:
                connection.execute(
                    """INSERT INTO task_attempts
                       (attempt_id, task_id, tenant_id, owner_id, outcome, payload)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        new_attempt.attempt_id,
                        task.task_id,
                        scope.tenant_id,
                        scope.owner_id,
                        new_attempt.outcome.value,
                        _dump(new_attempt.to_public_dict()),
                    ),
                )
            if close_attempt is not None:
                cursor = connection.execute(
                    """UPDATE task_attempts SET outcome=?, payload=?
                       WHERE attempt_id=? AND task_id=? AND tenant_id=? AND owner_id=?
                       AND outcome='running'""",
                    (
                        close_attempt.outcome.value,
                        _dump(close_attempt.to_public_dict()),
                        close_attempt.attempt_id,
                        task.task_id,
                        scope.tenant_id,
                        scope.owner_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise TaskWriteConflict("attempt_changed_concurrently")
            if update_attempt is not None:
                cursor = connection.execute(
                    """UPDATE task_attempts SET payload=?
                       WHERE attempt_id=? AND task_id=? AND tenant_id=? AND owner_id=?
                       AND outcome='running'""",
                    (
                        _dump(update_attempt.to_public_dict()),
                        update_attempt.attempt_id,
                        task.task_id,
                        scope.tenant_id,
                        scope.owner_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise TaskWriteConflict("attempt_changed_concurrently")
            self._insert_event(connection, scope, event)

    def get_attempt(self, scope: TaskScope, attempt_id: str) -> TaskAttempt | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM task_attempts
                   WHERE attempt_id=? AND tenant_id=? AND owner_id=?""",
                (attempt_id, scope.tenant_id, scope.owner_id),
            ).fetchone()
        return _attempt_from_json(row[0]) if row else None

    def list_attempts(self, scope: TaskScope, task_id: str) -> list[TaskAttempt]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM task_attempts
                   WHERE task_id=? AND tenant_id=? AND owner_id=? ORDER BY rowid""",
                (task_id, scope.tenant_id, scope.owner_id),
            ).fetchall()
        return [_attempt_from_json(row[0]) for row in rows]

    def append_checkpoint(
        self, scope: TaskScope, checkpoint: TaskCheckpoint, payload: dict[str, object]
    ) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO task_checkpoints
                   (checkpoint_id, task_id, tenant_id, owner_id, sequence, metadata, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    checkpoint.checkpoint_id,
                    checkpoint.task_id,
                    scope.tenant_id,
                    scope.owner_id,
                    checkpoint.sequence,
                    _dump(checkpoint.to_owner_dict()),
                    _dump(payload),
                ),
            )

    def save_checkpoint_transition(
        self,
        *,
        scope: TaskScope,
        prior_updated_at: str,
        task: DurableTask,
        event: TaskEvent,
        attempt: TaskAttempt,
        checkpoint: TaskCheckpoint,
        payload: dict[str, object],
    ) -> None:
        """Atomically persist a checkpoint and advance its owning task."""

        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """UPDATE durable_tasks SET state=?, updated_at=?, payload=?
                   WHERE task_id=? AND tenant_id=? AND owner_id=? AND updated_at=?""",
                (
                    task.state.value,
                    task.updated_at,
                    _dump(task.to_owner_dict()),
                    task.task_id,
                    scope.tenant_id,
                    scope.owner_id,
                    prior_updated_at,
                ),
            )
            if cursor.rowcount != 1:
                raise TaskWriteConflict("task_changed_concurrently")
            connection.execute(
                """INSERT INTO task_checkpoints
                   (checkpoint_id, task_id, tenant_id, owner_id, sequence, metadata, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    checkpoint.checkpoint_id,
                    checkpoint.task_id,
                    scope.tenant_id,
                    scope.owner_id,
                    checkpoint.sequence,
                    _dump(checkpoint.to_owner_dict()),
                    _dump(payload),
                ),
            )
            cursor = connection.execute(
                """UPDATE task_attempts SET payload=?
                   WHERE attempt_id=? AND task_id=? AND tenant_id=? AND owner_id=?
                   AND outcome='running'""",
                (
                    _dump(attempt.to_public_dict()),
                    attempt.attempt_id,
                    task.task_id,
                    scope.tenant_id,
                    scope.owner_id,
                ),
            )
            if cursor.rowcount != 1:
                raise TaskWriteConflict("attempt_changed_concurrently")
            self._insert_event(connection, scope, event)

    def latest_checkpoint(self, scope: TaskScope, task_id: str) -> TaskCheckpoint | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT metadata FROM task_checkpoints
                   WHERE task_id=? AND tenant_id=? AND owner_id=?
                   ORDER BY sequence DESC LIMIT 1""",
                (task_id, scope.tenant_id, scope.owner_id),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        value["payload_keys"] = tuple(value.get("payload_keys", ()))
        return TaskCheckpoint(**value)

    def checkpoint_payload(
        self, scope: TaskScope, checkpoint_id: str
    ) -> dict[str, object] | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM task_checkpoints
                   WHERE checkpoint_id=? AND tenant_id=? AND owner_id=?""",
                (checkpoint_id, scope.tenant_id, scope.owner_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def append_artifact(self, scope: TaskScope, artifact: TaskArtifact) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO task_artifacts
                   (artifact_id, task_id, tenant_id, owner_id, name, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    artifact.artifact_id,
                    artifact.task_id,
                    scope.tenant_id,
                    scope.owner_id,
                    artifact.name,
                    _dump(artifact.to_public_dict()),
                ),
            )

    def list_artifacts(self, scope: TaskScope, task_id: str) -> list[TaskArtifact]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM task_artifacts
                   WHERE task_id=? AND tenant_id=? AND owner_id=? ORDER BY rowid""",
                (task_id, scope.tenant_id, scope.owner_id),
            ).fetchall()
        return [TaskArtifact(**json.loads(row[0])) for row in rows]

    def reserve_effect(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        idempotency_key: str,
        attempt_id: str,
        created_at: str,
    ) -> tuple[str, str, str | None, bool]:
        """Atomically reserve an external effect or return its existing receipt."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT attempt_id, status, result_sha256 FROM task_effects
                   WHERE task_id=? AND tenant_id=? AND owner_id=? AND idempotency_key=?""",
                (task_id, scope.tenant_id, scope.owner_id, idempotency_key),
            ).fetchone()
            if row is not None:
                return row[0], row[1], row[2], False
            connection.execute(
                """INSERT INTO task_effects
                   (task_id, tenant_id, owner_id, idempotency_key, attempt_id, status,
                    result_sha256, created_at, committed_at)
                   VALUES (?, ?, ?, ?, ?, 'reserved', NULL, ?, NULL)""",
                (
                    task_id,
                    scope.tenant_id,
                    scope.owner_id,
                    idempotency_key,
                    attempt_id,
                    created_at,
                ),
            )
        return attempt_id, "reserved", None, True

    def commit_effect(
        self,
        *,
        scope: TaskScope,
        task_id: str,
        idempotency_key: str,
        attempt_id: str,
        result_sha256: str,
        committed_at: str,
    ) -> bool:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """UPDATE task_effects SET status='committed', result_sha256=?, committed_at=?
                   WHERE task_id=? AND tenant_id=? AND owner_id=? AND idempotency_key=?
                   AND attempt_id=? AND status='reserved'""",
                (
                    result_sha256,
                    committed_at,
                    task_id,
                    scope.tenant_id,
                    scope.owner_id,
                    idempotency_key,
                    attempt_id,
                ),
            )
        return cursor.rowcount == 1

    def list_events(self, scope: TaskScope, task_id: str) -> list[TaskEvent]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM task_events
                   WHERE task_id=? AND tenant_id=? AND owner_id=? ORDER BY rowid""",
                (task_id, scope.tenant_id, scope.owner_id),
            ).fetchall()
        return [TaskEvent(**json.loads(row[0])) for row in rows]

    def _insert_event(
        self, connection: sqlite3.Connection, scope: TaskScope, event: TaskEvent
    ) -> None:
        connection.execute(
            """INSERT INTO task_events
               (event_id, task_id, tenant_id, owner_id, occurred_at, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.task_id,
                scope.tenant_id,
                scope.owner_id,
                event.occurred_at,
                _dump(event.to_public_dict()),
            ),
        )

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS task_schema (
                  version TEXT PRIMARY KEY,
                  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS durable_tasks (
                  task_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  state TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_owner
                  ON durable_tasks(tenant_id, owner_id, state, updated_at);
                CREATE TABLE IF NOT EXISTS task_attempts (
                  attempt_id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  outcome TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  FOREIGN KEY(task_id) REFERENCES durable_tasks(task_id)
                );
                CREATE TABLE IF NOT EXISTS task_checkpoints (
                  checkpoint_id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  sequence INTEGER NOT NULL,
                  metadata TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  UNIQUE(task_id, sequence),
                  FOREIGN KEY(task_id) REFERENCES durable_tasks(task_id)
                );
                CREATE TABLE IF NOT EXISTS task_artifacts (
                  artifact_id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  FOREIGN KEY(task_id) REFERENCES durable_tasks(task_id)
                );
                CREATE TABLE IF NOT EXISTS task_effects (
                  task_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  idempotency_key TEXT NOT NULL,
                  attempt_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  result_sha256 TEXT,
                  created_at TEXT NOT NULL,
                  committed_at TEXT,
                  PRIMARY KEY(task_id, tenant_id, owner_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS task_events (
                  event_id TEXT PRIMARY KEY,
                  task_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  occurred_at TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  FOREIGN KEY(task_id) REFERENCES durable_tasks(task_id)
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO task_schema(version) VALUES (?)",
                (self.SCHEMA_VERSION,),
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


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _task_from_json(payload: str) -> DurableTask:
    value = json.loads(payload)
    value["scope"] = TaskScope(**value["scope"])
    value["state"] = TaskState(value["state"])
    for key in ("dependency_ids", "required_artifacts", "required_evidence"):
        value[key] = tuple(value.get(key, ()))
    return DurableTask(**value)


def _attempt_from_json(payload: str) -> TaskAttempt:
    value = json.loads(payload)
    value["outcome"] = AttemptOutcome(value["outcome"])
    return TaskAttempt(**value)
