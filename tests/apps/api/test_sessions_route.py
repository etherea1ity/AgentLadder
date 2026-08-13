from __future__ import annotations

import json

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


def test_session_detail_withholds_historical_provider_protocol_markup(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    assistant = MessageRecord(
        session_id=session.session_id,
        role="assistant",
        content='<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="lookup">',
        status="completed",
    )
    store.save_message(assistant)

    detail = get_session(session.session_id, store=store)

    assert len(detail.messages) == 1
    assert "DSML" not in detail.messages[0].content
    assert "withheld" in detail.messages[0].content


def test_session_detail_truncates_after_terminal_and_strips_legacy_raw_reasoning(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    user = MessageRecord(session_id=session.session_id, role="user", content="hello")
    assistant = MessageRecord(session_id=session.session_id, role="assistant", content="stopped")
    run = RunRecord(
        run_id="run-terminal-boundary",
        session_id=session.session_id,
        user_message_id=user.message_id,
        assistant_message_id=assistant.message_id,
        status="cancelled",
    )
    for message in (user, assistant):
        store.save_message(message)
    store.save_run(run)
    events = [
        RunEventRecord(
            run_id=run.run_id,
            event_type="llm_call_completed",
            message="Model call completed.",
            payload={
                "reasoning": {
                    "source": "message.reasoning_content",
                    "summary": "legacy hidden scratchpad",
                }
            },
        ),
        RunEventRecord(
            run_id=run.run_id,
            event_type="provider_reasoning_delta",
            message="Provider reasoning summary received.",
            payload={
                "source": "message.reasoning_content",
                "items": [{"body": "legacy hidden scratchpad"}],
            },
        ),
        RunEventRecord(run_id=run.run_id, event_type="run_cancelled", message="Stopped."),
        RunEventRecord(run_id=run.run_id, event_type="tool_call_started", message="Must not appear."),
    ]
    for event in events:
        store.append_event(event)

    detail = get_session(session.session_id, store=store)
    serialized = json.dumps([event.model_dump(mode="json") for event in detail.events])

    assert [event.event_type for event in detail.events] == [
        "llm_call_completed",
        "run_cancelled",
    ]
    assert "legacy hidden scratchpad" not in serialized
    assert "Must not appear" not in serialized
