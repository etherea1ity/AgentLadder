from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from apps.api.schemas import MessageRecord, RunEventRecord, RunRecord, SessionRecord, now_iso

T = TypeVar("T", bound=BaseModel)


class JsonlAppStore:
    """JSONL store for local learning mode. Writes append, delete purges related records."""

    def __init__(self, root: str | Path = "data/app") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.sessions_path = self.root / "sessions.jsonl"
        self.messages_path = self.root / "messages.jsonl"
        self.runs_path = self.root / "runs.jsonl"
        self.events_path = self.root / "run_events.jsonl"

    def create_session(self) -> SessionRecord:
        session = SessionRecord()
        self.save_session(session)
        return session

    def list_sessions(self) -> list[SessionRecord]:
        sessions = [s for s in self._load_latest(self.sessions_path, SessionRecord, "session_id").values() if not s.deleted_at]
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self._load_latest(self.sessions_path, SessionRecord, "session_id").get(session_id)

    def get_visible_session(self, session_id: str) -> SessionRecord | None:
        session = self.get_session(session_id)
        if session is None or session.deleted_at:
            return None
        return session

    def save_session(self, session: SessionRecord) -> None:
        self._append(self.sessions_path, session)

    def rename_session(self, session_id: str, title: str) -> SessionRecord | None:
        session = self.get_visible_session(session_id)
        if session is None:
            return None
        updated = session.model_copy(update={"title": title, "updated_at": now_iso()})
        self.save_session(updated)
        return updated

    def delete_session(self, session_id: str, trace_path: str | Path = "data/traces/runs.jsonl") -> SessionRecord | None:
        """Hard-delete a local learning conversation and every related app/trace record.

        The local app is single-user by default. The product delete action means the
        conversation should disappear from the UI *and* from local JSONL stores,
        not just receive a tombstone. We still return a transient deleted record
        so the API can acknowledge the deletion time.
        """
        session = self.get_visible_session(session_id)
        if session is None:
            return None
        deleted = session.model_copy(update={"deleted_at": now_iso(), "updated_at": now_iso()})
        run_ids = {run.run_id for run in self.list_runs(session_id)}
        message_ids = {message.message_id for message in self.list_messages(session_id)}
        with self._lock:
            self._rewrite_without(self.sessions_path, SessionRecord, lambda item: item.session_id == session_id)
            self._rewrite_without(self.messages_path, MessageRecord, lambda item: item.session_id == session_id or item.message_id in message_ids)
            self._rewrite_without(self.runs_path, RunRecord, lambda item: item.session_id == session_id or item.run_id in run_ids)
            self._rewrite_without(self.events_path, RunEventRecord, lambda item: item.run_id in run_ids)
            self._purge_traces(run_ids, trace_path)
        return deleted

    def save_message(self, message: MessageRecord) -> None:
        self._append(self.messages_path, message)
        session = self.get_session(message.session_id)
        if session and not session.deleted_at and message.message_id not in session.message_ids:
            ids = [*session.message_ids, message.message_id]
            self.save_session(session.model_copy(update={"message_ids": ids, "updated_at": now_iso()}))

    def update_message(self, message: MessageRecord) -> None:
        self._append(self.messages_path, message.model_copy(update={"updated_at": now_iso()}))
        session = self.get_session(message.session_id)
        if session and not session.deleted_at:
            self.save_session(session.model_copy(update={"updated_at": now_iso()}))

    def list_messages(self, session_id: str) -> list[MessageRecord]:
        messages = [m for m in self._load_latest(self.messages_path, MessageRecord, "message_id").values() if m.session_id == session_id]
        messages.sort(key=lambda item: item.created_at)
        return messages

    def get_message(self, message_id: str) -> MessageRecord | None:
        return self._load_latest(self.messages_path, MessageRecord, "message_id").get(message_id)

    def save_run(self, run: RunRecord) -> None:
        self._append(self.runs_path, run)

    def list_runs(self, session_id: str) -> list[RunRecord]:
        runs = [r for r in self._load_latest(self.runs_path, RunRecord, "run_id").values() if r.session_id == session_id]
        runs.sort(key=lambda item: item.started_at or "")
        return runs

    def get_run(self, run_id: str) -> RunRecord | None:
        return self._load_latest(self.runs_path, RunRecord, "run_id").get(run_id)

    def get_visible_run(self, run_id: str) -> RunRecord | None:
        run = self.get_run(run_id)
        if run is None or self.get_visible_session(run.session_id) is None:
            return None
        return run

    def append_event(self, event: RunEventRecord) -> None:
        self._append(self.events_path, event)

    def list_events(self, run_id: str) -> list[RunEventRecord]:
        return [event for event in self._load_all(self.events_path, RunEventRecord) if event.run_id == run_id]

    def latest_trace_for_run(self, run_id: str, trace_path: str | Path = "data/traces/runs.jsonl") -> dict | None:
        path = Path(trace_path)
        if not path.exists():
            return None
        result = None
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("run_id") == run_id:
                    result = record
        return result


    def _rewrite_without(self, path: Path, model_type: type[T], should_remove) -> None:
        if not path.exists():
            return
        kept = [item for item in self._load_all(path, model_type) if not should_remove(item)]
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as file:
            for item in kept:
                file.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n")
        tmp.replace(path)

    def _purge_traces(self, run_ids: set[str], trace_path: str | Path) -> None:
        if not run_ids:
            return
        path = Path(trace_path)
        if not path.exists():
            return
        kept: list[dict] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("run_id") not in run_ids:
                    kept.append(record)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as file:
            for record in kept:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp.replace(path)

    def _append(self, path: Path, model: BaseModel) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(model.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def _load_latest(self, path: Path, model_type: type[T], key: str) -> dict[str, T]:
        latest: dict[str, T] = {}
        for item in self._load_all(path, model_type):
            latest[getattr(item, key)] = item
        return latest

    def _load_all(self, path: Path, model_type: type[T]) -> list[T]:
        if not path.exists():
            return []
        items: list[T] = []
        with self._lock:
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if line.strip():
                        items.append(model_type.model_validate(json.loads(line)))
        return items
