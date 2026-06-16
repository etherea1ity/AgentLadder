from __future__ import annotations

import json

from apps.api.schemas import MessageRecord, RunEventRecord, RunRecord
from apps.api.services.app_store import JsonlAppStore


def test_delete_session_purges_related_messages_runs_events_and_traces(tmp_path) -> None:
    """Deleting a local conversation should remove its backend records."""

    store = JsonlAppStore(tmp_path / "app")
    trace_path = tmp_path / "traces" / "runs.jsonl"
    trace_path.parent.mkdir(parents=True)
    session = store.create_session()
    user = MessageRecord(
        message_id="msg_user",
        session_id=session.session_id,
        role="user",
        content="hello",
    )
    assistant = MessageRecord(
        message_id="msg_assistant",
        session_id=session.session_id,
        role="assistant",
        content="hi",
    )
    run = RunRecord(
        run_id="run_delete_me",
        session_id=session.session_id,
        user_message_id=user.message_id,
        assistant_message_id=assistant.message_id,
    )
    event = RunEventRecord(
        run_id=run.run_id,
        event_type="run_created",
        message="created",
    )

    store.save_message(user)
    store.save_message(assistant)
    store.save_run(run)
    store.append_event(event)
    trace_path.write_text(
        json.dumps({"run": {"run_id": run.run_id}, "type": "run.completed"})
        + "\n",
        encoding="utf-8",
    )

    deleted = store.delete_session(session.session_id, trace_path)

    assert deleted is not None
    assert deleted.deleted_at is not None
    assert store.get_visible_session(session.session_id) is None
    assert store.list_messages(session.session_id) == []
    assert store.list_runs(session.session_id) == []
    assert store.list_events(run.run_id) == []
    assert trace_path.read_text(encoding="utf-8") == ""
