"""SQLite persistence for team members, mailboxes, and worktree leases."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from typing import Iterator

from klara.teams.models import AgentKind, AgentStatus, MessageKind, TeamAgent, TeamMessage, TeamScope, WorktreeLease, WorktreeStatus


class SQLiteTeamRepository:
    SCHEMA_VERSION = "klara.teams.sqlite.v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def save_agent(self, agent: TeamAgent) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO team_agents(agent_id, tenant_id, owner_id, team_id, status, payload)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id) DO UPDATE SET status=excluded.status, payload=excluded.payload""",
                (agent.agent_id, agent.scope.tenant_id, agent.scope.owner_id, agent.scope.team_id, agent.status.value, _dump(agent.to_owner_dict())),
            )

    def get_agent(self, scope: TeamScope, agent_id: str) -> TeamAgent | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM team_agents WHERE agent_id=? AND tenant_id=? AND owner_id=? AND team_id=?",
                (agent_id, scope.tenant_id, scope.owner_id, scope.team_id),
            ).fetchone()
        return _agent(row[0]) if row else None

    def list_agents(self, scope: TeamScope) -> list[TeamAgent]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM team_agents WHERE tenant_id=? AND owner_id=? AND team_id=? ORDER BY rowid",
                (scope.tenant_id, scope.owner_id, scope.team_id),
            ).fetchall()
        return [_agent(row[0]) for row in rows]

    def append_message(self, message: TeamMessage) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO team_messages(message_id, tenant_id, owner_id, team_id, recipient_id, sequence, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (message.message_id, message.scope.tenant_id, message.scope.owner_id, message.scope.team_id, message.recipient_id, message.sequence, _dump(message.to_owner_dict())),
            )

    def next_sequence(self, scope: TeamScope, recipient_id: str) -> int:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT COALESCE(MAX(sequence), 0) FROM team_messages
                   WHERE tenant_id=? AND owner_id=? AND team_id=? AND recipient_id=?""",
                (scope.tenant_id, scope.owner_id, scope.team_id, recipient_id),
            ).fetchone()
        return int(row[0]) + 1

    def list_inbox(self, scope: TeamScope, recipient_id: str, *, after_sequence: int = 0) -> list[TeamMessage]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM team_messages WHERE tenant_id=? AND owner_id=? AND team_id=?
                   AND recipient_id=? AND sequence>? ORDER BY sequence""",
                (scope.tenant_id, scope.owner_id, scope.team_id, recipient_id, after_sequence),
            ).fetchall()
        return [_message(row[0]) for row in rows]

    def get_message(self, scope: TeamScope, recipient_id: str, message_id: str) -> TeamMessage | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload FROM team_messages WHERE message_id=? AND tenant_id=? AND owner_id=?
                   AND team_id=? AND recipient_id=?""",
                (message_id, scope.tenant_id, scope.owner_id, scope.team_id, recipient_id),
            ).fetchone()
        return _message(row[0]) if row else None

    def save_message(self, message: TeamMessage) -> None:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """UPDATE team_messages SET payload=? WHERE message_id=? AND tenant_id=? AND owner_id=?
                   AND team_id=? AND recipient_id=?""",
                (_dump(message.to_owner_dict()), message.message_id, message.scope.tenant_id, message.scope.owner_id, message.scope.team_id, message.recipient_id),
            )
            if cursor.rowcount != 1:
                raise LookupError("team_message_not_found")

    def save_worktree(self, worktree: WorktreeLease) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO team_worktrees(worktree_id, tenant_id, owner_id, team_id, task_id, status, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(worktree_id) DO UPDATE SET status=excluded.status, payload=excluded.payload""",
                (worktree.worktree_id, worktree.scope.tenant_id, worktree.scope.owner_id, worktree.scope.team_id, worktree.task_id, worktree.status.value, _dump(worktree.to_owner_dict())),
            )

    def get_worktree(self, scope: TeamScope, worktree_id: str) -> WorktreeLease | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM team_worktrees WHERE worktree_id=? AND tenant_id=? AND owner_id=? AND team_id=?",
                (worktree_id, scope.tenant_id, scope.owner_id, scope.team_id),
            ).fetchone()
        return _worktree(row[0]) if row else None

    def list_worktrees(self, scope: TeamScope) -> list[WorktreeLease]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM team_worktrees WHERE tenant_id=? AND owner_id=? AND team_id=? ORDER BY rowid DESC",
                (scope.tenant_id, scope.owner_id, scope.team_id),
            ).fetchall()
        return [_worktree(row[0]) for row in rows]

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS team_agents (
                  agent_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                  team_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_team_agents_scope ON team_agents(tenant_id, owner_id, team_id, status);
                CREATE TABLE IF NOT EXISTS team_messages (
                  message_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                  team_id TEXT NOT NULL, recipient_id TEXT NOT NULL, sequence INTEGER NOT NULL, payload TEXT NOT NULL,
                  UNIQUE(tenant_id, owner_id, team_id, recipient_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_team_inbox ON team_messages(tenant_id, owner_id, team_id, recipient_id, sequence);
                CREATE TABLE IF NOT EXISTS team_worktrees (
                  worktree_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                  team_id TEXT NOT NULL, task_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_team_worktree_scope ON team_worktrees(tenant_id, owner_id, team_id, status);
                """
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _scope(value: dict[str, str]) -> TeamScope:
    return TeamScope(**value)


def _agent(payload: str) -> TeamAgent:
    value = json.loads(payload)
    value["scope"] = _scope(value["scope"])
    value["kind"] = AgentKind(value["kind"])
    value["status"] = AgentStatus(value["status"])
    value["capability_names"] = tuple(value["capability_names"])
    return TeamAgent(**value)


def _message(payload: str) -> TeamMessage:
    value = json.loads(payload)
    value["scope"] = _scope(value["scope"])
    value["kind"] = MessageKind(value["kind"])
    return TeamMessage(**value)


def _worktree(payload: str) -> WorktreeLease:
    value = json.loads(payload)
    value["scope"] = _scope(value["scope"])
    value["status"] = WorktreeStatus(value["status"])
    return WorktreeLease(**value)
