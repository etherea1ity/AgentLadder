from __future__ import annotations

from apps.api.routes.sessions import get_session
from apps.api.schemas import MessageRecord, RunEventRecord, RunRecord
from apps.api.services.app_store import JsonlAppStore


def test_session_detail_includes_persisted_run_events(tmp_path) -> None:
    """Reloading a conversation should hydrate the frontend run surface."""

    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    user = MessageRecord(
        message_id="msg_user",
        session_id=session.session_id,
        role="user",
        content="what time is it?",
        status="completed",
    )
    assistant = MessageRecord(
        message_id="msg_assistant",
        session_id=session.session_id,
        role="assistant",
        content="It is 22:00.",
        run_id="run_trace",
        status="completed",
    )
    run = RunRecord(
        run_id="run_trace",
        session_id=session.session_id,
        user_message_id=user.message_id,
        assistant_message_id=assistant.message_id,
        status="completed",
        trace_saved=True,
    )
    event = RunEventRecord(
        event_id="evt_tool_started",
        run_id=run.run_id,
        event_type="tool_call_started",
        message="Klara is using current_time.",
        payload={"tool_call": {"id": "call_1", "name": "current_time"}},
    )

    store.save_message(user)
    store.save_message(assistant)
    store.save_run(run)
    store.append_event(event)

    detail = get_session(session.session_id, store=store)

    assert [item.run_id for item in detail.runs] == [run.run_id]
    assert [item.event_id for item in detail.events] == [event.event_id]
