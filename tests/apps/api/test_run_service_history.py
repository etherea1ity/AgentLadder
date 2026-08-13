from __future__ import annotations

import json
import threading

from apps.api.schemas import ClientContext, MessageRecord
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.app.user_context import UserContext
from klara.context.history import GENERATED_IMAGE_PLACEHOLDER
from klara.core.messages import ModelResponse
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope, TaskState


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


class CaptureLlm:
    """LLM fixture that captures the prompt boundary for assertions."""

    def __init__(self) -> None:
        self.system_prompt = ""
        self.messages = ()

    def complete(self, **kwargs: object) -> ModelResponse:
        self.system_prompt = str(kwargs["system_prompt"])
        self.messages = kwargs["messages"]
        return ModelResponse(content="ok")


class BlockingLlm:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(self, **_: object) -> ModelResponse:
        self.started.set()
        assert self.release.wait(timeout=5)
        return ModelResponse(content="This answer must not overwrite cancellation.")


class LeakingProtocolLlm:
    def complete(self, **_: object) -> ModelResponse:
        return ModelResponse(
            content='<｜DSML｜tool_calls><｜DSML｜invoke name="current_time">'
        )


def test_run_service_projects_chat_run_into_durable_task_and_cancellation_wins(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    llm = BlockingLlm()
    task_scope = TaskScope("tenant-test", "owner-test", "klara")
    task_service = DurableTaskService(
        SQLiteTaskRepository(tmp_path / "app" / "tasks.sqlite3")
    )
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=llm,
        task_service=task_service,
        task_scope=task_scope,
        answer_chunk_delay_ms=0,
    )

    created = service.create_run(session.session_id, "Do cancellable work")
    assert llm.started.wait(timeout=5)
    task_before_cancel = task_service.get(scope=task_scope, task_id=created.run_id)
    assert task_before_cancel.state is TaskState.RUNNING
    service.cancel_run(created.run_id)
    llm.release.set()
    service._threads[created.run_id].join(timeout=5)

    run = store.get_run(created.run_id)
    task = task_service.get(scope=task_scope, task_id=created.run_id)
    assistant = store.get_message(created.assistant_message_id)
    event_types = [item.event_type for item in store.list_events(created.run_id)]
    assert run is not None and run.status == "cancelled"
    assert task.state is TaskState.CANCELLED
    assert assistant is not None and assistant.status == "cancelled"
    assert "run_completed" not in event_types
    assert "run_failed" not in event_types
    cancel_index = event_types.index("run_cancelled")
    assert event_types[cancel_index:] == ["run_cancelled"]


def test_cancelled_scheduled_run_cannot_be_implicitly_restarted(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    llm = BlockingLlm()
    task_scope = TaskScope("tenant-test", "owner-test", "klara")
    task_service = DurableTaskService(
        SQLiteTaskRepository(tmp_path / "app" / "tasks.sqlite3")
    )
    task_service.create(
        scope=task_scope,
        task_id="scheduled-task",
        title="Scheduled work",
        description="Do cancellable scheduled work",
    )
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=llm,
        task_service=task_service,
        task_scope=task_scope,
        answer_chunk_delay_ms=0,
    )

    created = service.create_scheduled_run(
        session_id=session.session_id,
        task_id="scheduled-task",
        question="Do cancellable scheduled work",
        schedule_title="Scheduled work",
    )
    assert llm.started.wait(timeout=5)
    worker = service._threads[created.run_id]
    service.cancel_run(created.run_id)
    llm.release.set()
    worker.join(timeout=5)

    replayed = service.create_scheduled_run(
        session_id=session.session_id,
        task_id="scheduled-task",
        question="Do cancellable scheduled work",
        schedule_title="Scheduled work",
    )
    event_types = [item.event_type for item in store.list_events(created.run_id)]
    assert replayed.status == "cancelled"
    assert created.run_id not in service._threads
    assert event_types[event_types.index("run_cancelled") :] == ["run_cancelled"]


def test_run_service_never_streams_internal_provider_protocol(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=LeakingProtocolLlm(),
        answer_chunk_delay_ms=0,
    )

    created = service.create_run(session.session_id, "Use a tool")
    service._threads[created.run_id].join(timeout=5)

    run = store.get_run(created.run_id)
    assistant = store.get_message(created.assistant_message_id)
    events = store.list_events(created.run_id)
    assert run is not None and run.status == "failed"
    assert run.error is not None and run.error.code == "provider_tool_protocol_invalid"
    assert assistant is not None and "DSML" not in assistant.content
    assert not any(event.event_type == "answer_delta" for event in events)


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


def test_current_user_message_prefers_client_time_context(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=FinalLlm(),
        user_context=UserContext(
            user_id="local-user",
            display_name="Local User",
            timezone="UTC",
            storage_key="local-user",
        ),
    )
    current_user = MessageRecord(
        session_id=session.session_id,
        role="user",
        content="What happened today?",
        status="completed",
        created_at="2026-06-18T12:34:56+00:00",
        client_created_at="2026-06-25T10:00:00+02:00",
        client_timezone="Asia/Shanghai",
    )

    assert (
        service._model_visible_content(current_user)
        == "[Thu 2026-06-25 16:00 GMT+08] What happened today?"
    )


def test_create_run_passes_browser_time_context_to_model_prompt(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    llm = CaptureLlm()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=llm,
        default_model="test-model",
        answer_chunk_delay_ms=0,
    )

    created = service.create_run(
        session.session_id,
        "Today status?",
        client_context=ClientContext(
            timestamp="2026-06-25T10:00:00+02:00",
            timezone="Asia/Shanghai",
            utc_offset_minutes=120,
        ),
    )
    service._threads[created.run_id].join(timeout=5)

    user_message = store.get_message(created.user_message_id)
    assert user_message is not None
    assert user_message.client_created_at == "2026-06-25T10:00:00+02:00"
    assert user_message.client_timezone == "Asia/Shanghai"
    assert "Conversation date: Thursday, June 25, 2026" in llm.system_prompt
    assert "User timezone: Asia/Shanghai" in llm.system_prompt
    assert llm.messages[0].content.startswith("[Thu 2026-06-25 16:00 GMT+08] ")


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
    frozen = next(
        event for event in events if event.event_type == "run_profile_frozen"
    )
    completed = next(event for event in events if event.event_type == "run_completed")

    assert run is not None
    assert run.status == "completed"
    assert run.trace_saved is True
    assert llm_started.payload["model"] == "test-model"
    assert frozen.payload["schema_version"] == "klara.run-profile.v1"
    assert frozen.payload["model"] == "test-model"
    assert frozen.payload["trace_sink"] == "jsonl"
    assert frozen.payload["profile_sha256"]
    assert not any(
        marker in json.dumps(frozen.payload).lower()
        for marker in ("api_key", "password", "secret")
    )
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
