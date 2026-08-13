"""SQLite persistence for permission requests, grants, and audits."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import threading
from typing import Iterator

from klara.core.tools import ToolSideEffect
from klara.permissions.models import (
    PermissionAction,
    PermissionAuditEvent,
    PermissionEffect,
    PermissionGrant,
    PermissionGrantStatus,
    PermissionRequest,
    PermissionRequestStatus,
    PermissionRisk,
    PermissionScope,
)


class SQLitePermissionRepository:
    """Persist permission state with owner partitioning and atomic consumption."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def save_request(self, request: PermissionRequest) -> None:
        payload = _dump(request.to_owner_dict())
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO permission_requests
                   (request_id, tenant_id, actor_id, fingerprint, status, updated_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(request_id) DO UPDATE SET
                     status=excluded.status, updated_at=excluded.updated_at, payload=excluded.payload""",
                (
                    request.request_id,
                    request.scope.tenant_id,
                    request.scope.actor_id,
                    request.fingerprint,
                    request.status.value,
                    request.updated_at,
                    payload,
                ),
            )

    def get_request(self, scope: PermissionScope, request_id: str) -> PermissionRequest | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM permission_requests
                   WHERE request_id=? AND tenant_id=? AND actor_id=?""",
                (request_id, scope.tenant_id, scope.actor_id),
            ).fetchone()
        return _request_from_json(row[0]) if row else None

    def find_pending(self, scope: PermissionScope, fingerprint: str) -> PermissionRequest | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM permission_requests
                   WHERE tenant_id=? AND actor_id=? AND fingerprint=? AND status='pending'
                   ORDER BY updated_at DESC LIMIT 1""",
                (scope.tenant_id, scope.actor_id, fingerprint),
            ).fetchone()
        return _request_from_json(row[0]) if row else None

    def list_requests(self, scope: PermissionScope) -> list[PermissionRequest]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM permission_requests
                   WHERE tenant_id=? AND actor_id=? ORDER BY updated_at DESC, request_id""",
                (scope.tenant_id, scope.actor_id),
            ).fetchall()
        return [_request_from_json(row[0]) for row in rows]

    def save_grant(self, grant: PermissionGrant) -> None:
        payload = _dump(grant.to_owner_dict())
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO permission_grants
                   (grant_id, tenant_id, actor_id, status, expires_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(grant_id) DO UPDATE SET
                     status=excluded.status, expires_at=excluded.expires_at, payload=excluded.payload""",
                (
                    grant.grant_id,
                    grant.scope.tenant_id,
                    grant.scope.actor_id,
                    grant.status.value,
                    grant.expires_at,
                    payload,
                ),
            )

    def get_grant(self, scope: PermissionScope, grant_id: str) -> PermissionGrant | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM permission_grants
                   WHERE grant_id=? AND tenant_id=? AND actor_id=?""",
                (grant_id, scope.tenant_id, scope.actor_id),
            ).fetchone()
        return _grant_from_json(row[0]) if row else None

    def list_grants(self, scope: PermissionScope) -> list[PermissionGrant]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM permission_grants
                   WHERE tenant_id=? AND actor_id=? ORDER BY rowid DESC, grant_id""",
                (scope.tenant_id, scope.actor_id),
            ).fetchall()
        return [_grant_from_json(row[0]) for row in rows]

    def consume_once(self, scope: PermissionScope, grant_id: str) -> PermissionGrant | None:
        """Atomically consume one use so concurrent calls cannot reuse authority."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM permission_grants
                   WHERE grant_id=? AND tenant_id=? AND actor_id=?""",
                (grant_id, scope.tenant_id, scope.actor_id),
            ).fetchone()
            if row is None:
                return None
            grant = _grant_from_json(row[0])
            if (
                grant.status is not PermissionGrantStatus.ACTIVE
                or grant.effect is not PermissionEffect.ALLOW_ONCE
                or grant.remaining_uses != 1
            ):
                return None
            consumed = replace(
                grant,
                status=PermissionGrantStatus.CONSUMED,
                remaining_uses=0,
            )
            connection.execute(
                "UPDATE permission_grants SET status=?, payload=? WHERE grant_id=?",
                (consumed.status.value, _dump(consumed.to_owner_dict()), grant_id),
            )
        return consumed

    def append_audit(self, event: PermissionAuditEvent) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO permission_audit
                   (audit_id, tenant_id, actor_id, occurred_at, payload)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    event.audit_id,
                    event.tenant_id,
                    event.actor_id,
                    event.occurred_at,
                    _dump(event.to_owner_dict()),
                ),
            )

    def list_audit(self, scope: PermissionScope) -> list[PermissionAuditEvent]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM permission_audit
                   WHERE tenant_id=? AND actor_id=? ORDER BY occurred_at DESC, audit_id""",
                (scope.tenant_id, scope.actor_id),
            ).fetchall()
        return [PermissionAuditEvent(**json.loads(row[0])) for row in rows]

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS permission_requests (
                  request_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  actor_id TEXT NOT NULL,
                  fingerprint TEXT NOT NULL,
                  status TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_permission_request_owner
                  ON permission_requests(tenant_id, actor_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_permission_request_fingerprint
                  ON permission_requests(tenant_id, actor_id, fingerprint, status);
                CREATE TABLE IF NOT EXISTS permission_grants (
                  grant_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  actor_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_permission_grant_owner
                  ON permission_grants(tenant_id, actor_id, status, expires_at);
                CREATE TABLE IF NOT EXISTS permission_audit (
                  audit_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  actor_id TEXT NOT NULL,
                  occurred_at TEXT NOT NULL,
                  payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_permission_audit_owner
                  ON permission_audit(tenant_id, actor_id, occurred_at);
                """
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


def _scope(value: dict[str, object]) -> PermissionScope:
    return PermissionScope(**value)


def _action(value: dict[str, object]) -> PermissionAction:
    return PermissionAction(
        **{
            **value,
            "side_effect": ToolSideEffect(value["side_effect"]),
            "risk": PermissionRisk(value["risk"]),
        }
    )


def _request_from_json(payload: str) -> PermissionRequest:
    value = json.loads(payload)
    value["scope"] = _scope(value["scope"])
    value["action"] = _action(value["action"])
    value["status"] = PermissionRequestStatus(value["status"])
    if value.get("decision_effect") is not None:
        value["decision_effect"] = PermissionEffect(value["decision_effect"])
    return PermissionRequest(**value)


def _grant_from_json(payload: str) -> PermissionGrant:
    value = json.loads(payload)
    value["scope"] = _scope(value["scope"])
    value["action"] = _action(value["action"])
    value["effect"] = PermissionEffect(value["effect"])
    value["status"] = PermissionGrantStatus(value["status"])
    return PermissionGrant(**value)
