from __future__ import annotations

from apps.api.schemas import MessageRecord
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.app.user_context import UserContext
from klara.context.history import GENERATED_IMAGE_PLACEHOLDER
from klara.core.messages import ModelResponse


class FinalLlm:
    """Tiny LLM fixture; this test only needs RunService construction."""

    def complete(self, **_: object) -> ModelResponse:
        """Return a final answer if the fixture is accidentally invoked."""

        return ModelResponse(content="ok")


class UsageLlm:
    """Tiny LLM fixture that reports token usage."""

    def complete(self, **_: object) -> ModelResponse:
        """Return a final answer with provider usage."""

        return ModelResponse(
            content="ok",
            usage={"input_tokens": 5, "output_tokens": 8},
        )


def test_conversation_history_uses_completed_messages_before_current_turn(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=FinalLlm(),
        user_context=UserContext.local_default(),
    )

    previous_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="draw Klara",
        status="completed",
        created_at="2026-06-18T12:34:56+00:00",
    )
    previous_assistant = MessageRecord(
        session_id=session.session_id,
        role="assistant",
        content="I can make that image.",
        status="completed",
        created_at="2026-06-18T12:35:56+00:00",
    )
    current_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="generate it",
        status="completed",
        created_at="2026-06-18T12:36:56+00:00",
    )
    pending_assistant = MessageRecord(
        session_id=session.session_id,
        role="assistant",
        content="",
        status="running",
    )
    for message in (previous_user, previous_assistant, current_user, pending_assistant):
        store.save_message(message)

    history = service._conversation_history(
        session.session_id,
        before_message_id=current_user.message_id,
    )

    assert [(message.role, message.content) for message in history] == [
        ("user", "[Thu 2026-06-18 12:34 UTC] draw Klara"),
        ("assistant", "I can make that image."),
    ]


def test_conversation_history_removes_local_generated_image_urls(tmp_path) -> None:
    """Prior local image assets should not pollute later unrelated tool choices."""

    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(store=store, bus=SSEBus(), llm_client=FinalLlm())

    previous_assistant = MessageRecord(
        session_id=session.session_id,
        role="assistant",
        content=(
            "[Open generated image]"
            "(/api/assets/local?path=data/assets/images/20260617/generated.png)"
        ),
        status="completed",
    )
    current_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="search the latest public news",
        status="completed",
    )
    for message in (previous_assistant, current_user):
        store.save_message(message)

    history = service._conversation_history(
        session.session_id,
        before_message_id=current_user.message_id,
    )

    assert len(history) == 1
    assert history[0].content == GENERATED_IMAGE_PLACEHOLDER


def test_current_user_message_is_timestamped_for_model_boundary(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=FinalLlm(),
        user_context=UserContext(
            user_id="local-user",
            display_name="Local User",
            timezone="Asia/Shanghai",
            storage_key="local-user",
        ),
    )
    current_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="Public event status?",
        status="completed",
        created_at="2026-06-18T12:34:56+00:00",
    )

    assert (
        service._model_visible_content(current_user)
        == "[Thu 2026-06-18 20:34 GMT+08] Public event status?"
    )
    assert current_user.content == "Public event status?"


def test_run_service_projects_model_and_trace_saved(tmp_path) -> None:
    """Completed app runs should expose model and trace persistence in events."""

    store = JsonlAppStore(tmp_path / "app")
    trace_path = tmp_path / "traces" / "runs.jsonl"
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=FinalLlm(),
        trace_path=str(trace_path),
        default_model="test-model",
    )

    created = service.create_run(session.session_id, "hello")
    thread = service._threads[created.run_id]
    thread.join(timeout=5)

    run = store.get_run(created.run_id)
    events = store.list_events(created.run_id)
    llm_started = next(
        event for event in events if event.event_type == "llm_call_started"
    )
    completed = next(event for event in events if event.event_type == "run_completed")

    assert run is not None
    assert run.status == "completed"
    assert run.trace_saved is True
    assert llm_started.payload["model"] == "test-model"
    assert completed.payload["trace_saved"] is True
    assert store.latest_trace_for_run(created.run_id, trace_path) is not None


def test_run_completed_payload_exposes_latency_and_tokens(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=UsageLlm(),
        default_model="test-model",
    )

    created = service.create_run(session.session_id, "hello")
    thread = service._threads[created.run_id]
    thread.join(timeout=5)

    run = store.get_run(created.run_id)
    completed = next(
        event
        for event in store.list_events(created.run_id)
        if event.event_type == "run_completed"
    )
    metrics = completed.payload["metrics"]

    assert run is not None
    assert run.status == "completed"
    assert isinstance(metrics["latency_ms"], int)
    assert metrics["latency_ms"] >= 0
    assert metrics["prompt_tokens"] == 5
    assert metrics["completion_tokens"] == 8
    assert metrics["total_tokens"] == 13
    assert metrics["token_source"] == "reported"
    assert completed.payload["prompt_tokens"] == 5
    assert completed.payload["completion_tokens"] == 8
    assert completed.payload["total_tokens"] == 13
    assert completed.payload["token_source"] == "reported"
