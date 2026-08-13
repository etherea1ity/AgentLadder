"""SQLite persistence for MCP configuration and content-free audit events."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from typing import Iterator

from klara.mcp.models import McpAuditEvent, McpServerConfig, McpTransportKind
from klara.permissions import PermissionScope


class SQLiteMcpRepository:
    SCHEMA_VERSION = "klara.mcp.sqlite.v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def save_server(self, config: McpServerConfig) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO mcp_servers(server_id,tenant_id,actor_id,updated_at,payload)
                   VALUES(?,?,?,?,?) ON CONFLICT(server_id) DO UPDATE SET
                   tenant_id=excluded.tenant_id,actor_id=excluded.actor_id,
                   updated_at=excluded.updated_at,payload=excluded.payload""",
                (
                    config.server_id,
                    config.scope.tenant_id,
                    config.scope.actor_id,
                    config.updated_at,
                    _dump(_config_payload(config)),
                ),
            )

    def get_server(self, scope: PermissionScope, server_id: str) -> McpServerConfig | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM mcp_servers WHERE server_id=? AND tenant_id=? AND actor_id=?",
                (server_id, scope.tenant_id, scope.actor_id),
            ).fetchone()
        return _config(row[0]) if row else None

    def list_servers(self, scope: PermissionScope) -> list[McpServerConfig]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM mcp_servers WHERE tenant_id=? AND actor_id=? ORDER BY updated_at DESC",
                (scope.tenant_id, scope.actor_id),
            ).fetchall()
        return [_config(row[0]) for row in rows]

    def delete_server(self, scope: PermissionScope, server_id: str) -> bool:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM mcp_servers WHERE server_id=? AND tenant_id=? AND actor_id=?",
                (server_id, scope.tenant_id, scope.actor_id),
            )
        return cursor.rowcount == 1

    def append_audit(self, event: McpAuditEvent) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO mcp_audit(event_id,server_id,tenant_id,actor_id,occurred_at,payload)
                   VALUES(?,?,?,?,?,?)""",
                (event.event_id, event.server_id, event.tenant_id, event.actor_id, event.occurred_at, _dump(event.to_public_dict())),
            )

    def list_audit(self, scope: PermissionScope, server_id: str | None = None) -> list[McpAuditEvent]:
        query = "SELECT payload FROM mcp_audit WHERE tenant_id=? AND actor_id=?"
        values: list[str] = [scope.tenant_id, scope.actor_id]
        if server_id:
            query += " AND server_id=?"
            values.append(server_id)
        query += " ORDER BY occurred_at DESC,event_id"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return [McpAuditEvent(**json.loads(row[0])) for row in rows]

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS mcp_schema(version TEXT PRIMARY KEY,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS mcp_servers(server_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,actor_id TEXT NOT NULL,updated_at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_mcp_server_owner ON mcp_servers(tenant_id,actor_id,updated_at);
                CREATE TABLE IF NOT EXISTS mcp_audit(event_id TEXT PRIMARY KEY,server_id TEXT NOT NULL,tenant_id TEXT NOT NULL,actor_id TEXT NOT NULL,occurred_at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_mcp_audit_owner ON mcp_audit(tenant_id,actor_id,occurred_at);
                """
            )
            connection.execute("INSERT OR IGNORE INTO mcp_schema(version) VALUES(?)", (self.SCHEMA_VERSION,))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
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


def _config_payload(config: McpServerConfig) -> dict[str, object]:
    value = config.to_owner_dict()
    value["env_refs"] = dict(config.env_refs)
    value.pop("env_ref_names", None)
    return value


def _config(payload: str) -> McpServerConfig:
    value = json.loads(payload)
    value["scope"] = PermissionScope(**value["scope"])
    value["transport"] = McpTransportKind(value["transport"])
    value["args"] = tuple(value.get("args", ()))
    return McpServerConfig(**value)
