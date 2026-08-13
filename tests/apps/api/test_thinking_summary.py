from __future__ import annotations

from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.core.messages import KlaraMessage, ModelCallError, ModelResponse
from klara.core.tools import ToolCall


class RecordingFinalLlm:
    """Main model fixture that records model-visible messages."""

    def __init__(self, answer: str = "final answer") -> None:
        """Create a final-answer fixture."""

        self.answer = answer
        self.calls: list[tuple[KlaraMessage, ...]] = []
        self.thinking_seen: list[bool | None] = []

    def complete(self, **kwargs: object) -> ModelResponse:
        """Return one final answer while recording the transcript."""

        self.calls.append(kwargs["messages"])  # type: ignore[index]
        self.thinking_seen.append(kwargs.get("thinking_enabled"))  # type: ignore[arg-type]
        return ModelResponse(content=self.answer)


class ReasoningFinalLlm(RecordingFinalLlm):
    """Main model fixture that returns provider-visible reasoning metadata."""

    def complete(self, **kwargs: object) -> ModelResponse:
        """Return final text plus provider reasoning metadata."""

        self.calls.append(kwargs["messages"])  # type: ignore[index]
        return ModelResponse(
            content="final answer",
            reasoning_summary="The provider returned a safe summary of model thinking.",
            reasoning_source="message.reasoning_summary",
        )


class ToolThenFinalLlm:
    """Main model fixture that requests one tool before finalizing."""

    def __init__(self) -> None:
        """Create a two-turn tool fixture."""

        self.calls = 0
        self.histories: list[tuple[KlaraMessage, ...]] = []

    def complete(self, **kwargs: object) -> ModelResponse:
        """Request a tool on the first call and answer on the second."""

        self.calls += 1
        self.histories.append(kwargs["messages"])  # type: ignore[index]
        if self.calls == 1:
            return ModelResponse(
                content="I will check the current time first.",
                tool_calls=(
                    ToolCall(
                        id="call_time",
                        name="current_time",
                        arguments={"timezone": "Asia/Shanghai"},
                    ),
                ),
            )
        return ModelResponse(content="It is time to answer.")


class ToolThenFailureLlm:
    """Main model fixture that emits public activity before a later failure."""

    def __init__(self) -> None:
        """Create a fixture that fails after the first tool turn."""

        self.calls = 0

    def complete(self, **_: object) -> ModelResponse:
        """Return one tool request, then simulate a provider failure."""

        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content="I will check a tool before continuing.",
                tool_calls=(
                    ToolCall(
                        id="call_time",
                        name="current_time",
                        arguments={"timezone": "Asia/Shanghai"},
                    ),
                ),
            )
        raise RuntimeError("provider request failed: The read operation timed out")


class TypedProviderFailureLlm:
    """Provider failure fixture whose private text must stay server-side."""

    def complete(self, **_: object) -> ModelResponse:
        raise ModelCallError(
            "upstream body contains private-account-id-123",
            code="provider_unavailable",
            retryable=True,
            status_code=503,
        )


def test_thinking_summary_started_and_completed_wrap_answer(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=RecordingFinalLlm(),
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)

    events = store.list_events(created.run_id)
    started = next(event for event in events if event.event_type == "thinking_summary_started")
    completed = next(event for event in events if event.event_type == "thinking_summary_completed")
    answer_started = next(event for event in events if event.event_type == "answer_streaming_started")

    assert events.index(started) < events.index(answer_started)
    assert events.index(completed) < events.index(answer_started)
    assert started.payload["presentation"] == "gpt_style_collapsible"
    assert isinstance(completed.payload["duration_ms"], int)
    assert completed.payload["has_summary"] is False


def test_run_service_uses_configured_default_thinking(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    llm = RecordingFinalLlm()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=llm,
        allowed_models={"qwen/qwen-flash"},
        thinking_support={"qwen/qwen-flash": True},
        default_thinking={"qwen/qwen-flash": False},
        default_model="qwen/qwen-flash",
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello", thinking_enabled=True)
    service._threads[created.run_id].join(timeout=5)

    run = store.get_run(created.run_id)
    assert run is not None
    assert run.thinking_enabled is True
    assert llm.thinking_seen == [True]


def test_run_service_rejects_thinking_for_unsupported_model(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=RecordingFinalLlm(),
        allowed_models={"deepseek/deepseek-v4-flash"},
        thinking_support={"deepseek/deepseek-v4-flash": False},
        default_model="deepseek/deepseek-v4-flash",
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    try:
        service.create_run(
            session.session_id,
            "hello",
            model="deepseek/deepseek-v4-flash",
            thinking_enabled=True,
        )
    except ValueError as exc:
        assert str(exc) == "thinking_not_supported"
    else:
        raise AssertionError("Expected unsupported thinking to fail")


def test_run_service_does_not_emit_legacy_public_summary_events(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=RecordingFinalLlm(),
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)

    event_types = {event.event_type for event in store.list_events(created.run_id)}
    assert "thinking_summary_delta" not in event_types


def test_provider_reasoning_delta_does_not_enter_assistant_content_or_history(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    llm = ReasoningFinalLlm()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=llm,
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    first = service.create_run(session.session_id, "first")
    service._threads[first.run_id].join(timeout=5)
    second = service.create_run(session.session_id, "second")
    service._threads[second.run_id].join(timeout=5)

    first_events = store.list_events(first.run_id)
    deltas = [event for event in first_events if event.event_type == "provider_reasoning_delta"]
    assert deltas
    assert deltas[0].payload["items"][0]["source"] == "provider_reasoning"

    assistant = store.get_message(first.assistant_message_id)
    assert assistant is not None
    assert assistant.content == "final answer"
    assert "provider returned" not in assistant.content.lower()

    second_history = llm.calls[-1]
    assert all("provider returned" not in message.content.lower() for message in second_history)


def test_activity_facts_stay_debug_only_and_do_not_enter_assistant_content(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=ToolThenFinalLlm(),
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "what time is it in Shanghai?")
    service._threads[created.run_id].join(timeout=5)

    events = store.list_events(created.run_id)
    assert [event for event in events if event.event_type == "activity_fact_recorded"]
    assistant = store.get_message(created.assistant_message_id)
    assert assistant is not None
    assert assistant.content == "It is time to answer."
    assert "activity_fact_recorded" not in assistant.content


def test_tool_call_content_emits_assistant_activity_without_entering_history(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    llm = ToolThenFinalLlm()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=llm,
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
        answer_chunk_delay_ms=0,
    )

    first = service.create_run(session.session_id, "what time is it in Shanghai?")
    service._threads[first.run_id].join(timeout=5)
    second = service.create_run(session.session_id, "continue")
    service._threads[second.run_id].join(timeout=5)

    events = store.list_events(first.run_id)
    activity = [event for event in events if event.event_type == "assistant_activity_delta"]
    assert activity
    assert activity[0].payload["text"] == "I will check the current time first."
    assert activity[0].payload["phase"] == "before_tool"

    assistant = store.get_message(first.assistant_message_id)
    assert assistant is not None
    assert assistant.content == "It is time to answer."
    assert "I will check the current time first." not in assistant.content

    # The second run should see only completed user/assistant content, not activity.
    assert all(
        "I will check the current time first." not in message.content
        for message in llm.histories[-1]
    )


def test_failed_run_keeps_prior_activity_events_and_exposes_latency(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=ToolThenFailureLlm(),
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
        answer_chunk_delay_ms=0,
    )

    created = service.create_run(session.session_id, "what time is it in Shanghai?")
    service._threads[created.run_id].join(timeout=5)

    events = store.list_events(created.run_id)
    failed = next(event for event in events if event.event_type == "run_failed")
    activity = [
        event for event in events if event.event_type == "assistant_activity_delta"
    ]
    run = store.get_run(created.run_id)
    assistant = store.get_message(created.assistant_message_id)

    assert activity
    assert activity[0].payload["text"] == "I will check a tool before continuing."
    assert isinstance(failed.payload["latency_ms"], int)
    assert run is not None
    assert run.status == "failed"
    assert run.latency_ms == failed.payload["latency_ms"]
    assert assistant is not None
    assert assistant.status == "failed"


def test_typed_provider_failure_uses_safe_app_error_contract(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=TypedProviderFailureLlm(),
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
        answer_chunk_delay_ms=0,
    )

    created = service.create_run(session.session_id, "trigger typed failure")
    service._threads[created.run_id].join(timeout=5)

    run = store.get_run(created.run_id)
    failed = next(
        event
        for event in store.list_events(created.run_id)
        if event.event_type == "run_failed"
    )
    assert run is not None and run.error is not None
    assert run.error.code == "provider_unavailable"
    assert run.error.message == "The model provider is temporarily unavailable."
    assert "private-account-id" not in run.model_dump_json()
    assert "private-account-id" not in failed.model_dump_json()


def test_long_answer_emits_multiple_display_chunks(tmp_path) -> None:
    answer = "This is a longer answer that should stream in several small display chunks."
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=RecordingFinalLlm(answer),
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
        answer_chunk_delay_ms=0,
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)

    events = store.list_events(created.run_id)
    chunks = [event.payload["delta"] for event in events if event.event_type == "answer_delta"]
    assistant = store.get_message(created.assistant_message_id)
    assert len(chunks) > 1
    assert "".join(str(chunk) for chunk in chunks) == answer
    assert assistant is not None
    assert assistant.content == answer
