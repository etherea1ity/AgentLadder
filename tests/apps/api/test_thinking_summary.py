from __future__ import annotations

import json

from apps.api.schemas import RunEventRecord
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from apps.api.services.workstream_narrator import (
    ThinkingSummaryInput,
    ThinkingSummaryNarrator,
)
from klara.core.messages import KlaraMessage, ModelResponse


class RecordingFinalLlm:
    """Main model fixture that records model-visible messages."""

    def __init__(self) -> None:
        self.calls: list[tuple[KlaraMessage, ...]] = []

    def complete(self, **kwargs: object) -> ModelResponse:
        self.calls.append(kwargs["messages"])  # type: ignore[index]
        return ModelResponse(content="final answer")


class SummaryNarratorLlm:
    """Narrator fixture that returns a valid thinking summary."""

    def __init__(self, summary: str) -> None:
        self.summary = summary
        self.inputs: list[dict[str, object]] = []

    def complete(self, **kwargs: object) -> ModelResponse:
        messages = kwargs["messages"]  # type: ignore[index]
        payload = json.loads(messages[0].content)
        self.inputs.append(payload)
        evidence_id = payload["events"][0]["event_id"]
        return ModelResponse(
            content=json.dumps(
                {
                    "summary": self.summary,
                    "evidence_event_ids": [evidence_id],
                    "confidence": 0.82,
                }
            )
        )


class StaticNarratorLlm:
    """Narrator fixture that returns one fixed response."""

    def __init__(self, content: str) -> None:
        self.content = content

    def complete(self, **_: object) -> ModelResponse:
        return ModelResponse(content=self.content)


class BrokenNarratorLlm:
    """Narrator fixture that fails."""

    def complete(self, **_: object) -> ModelResponse:
        raise RuntimeError("narrator broke")


def test_thinking_summary_started_emitted_near_run_start(tmp_path) -> None:
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
    llm_started = next(event for event in events if event.event_type == "llm_call_started")

    assert events.index(started) < events.index(llm_started)
    assert started.payload["presentation"] == "gpt_style_collapsible"


def test_thinking_summary_completed_before_answer_streaming_started(tmp_path) -> None:
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
    completed = next(
        event for event in events if event.event_type == "thinking_summary_completed"
    )
    answer_started = next(
        event for event in events if event.event_type == "answer_streaming_started"
    )

    assert events.index(completed) < events.index(answer_started)
    assert isinstance(completed.payload["duration_ms"], int)
    assert completed.payload["has_summary"] is False


def test_fake_narrator_summary_appears_as_thinking_summary_delta(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    narrator = SummaryNarratorLlm(
        "Klara reviewed the public run trace before writing the answer."
    )
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=RecordingFinalLlm(),
        default_model="main-model",
        narrator_client=narrator,
        narrator_model="narrator-model",
        enable_workstream_narrator=True,
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)

    events = store.list_events(created.run_id)
    delta = next(event for event in events if event.event_type == "thinking_summary_delta")
    completed = next(
        event for event in events if event.event_type == "thinking_summary_completed"
    )

    assert delta.payload["text"] == "Klara reviewed the public run trace before writing the answer."
    assert delta.payload["source"] == "narrator_model"
    assert completed.payload["has_summary"] is True
    assert narrator.inputs[0]["run_status"] == "completed"


def test_thinking_summary_delta_does_not_enter_assistant_message_content(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    main_llm = RecordingFinalLlm()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=main_llm,
        default_model="main-model",
        narrator_client=SummaryNarratorLlm("Klara summarized the public trace."),
        narrator_model="narrator-model",
        enable_workstream_narrator=True,
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)
    assistant = store.get_message(created.assistant_message_id)

    assert assistant is not None
    assert assistant.content == "final answer"
    assert "public trace" not in main_llm.calls[0][0].content


def test_thinking_summary_narrator_failure_does_not_fail_run(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=RecordingFinalLlm(),
        default_model="main-model",
        narrator_client=BrokenNarratorLlm(),
        narrator_model="narrator-model",
        enable_workstream_narrator=True,
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)

    run = store.get_run(created.run_id)
    events = store.list_events(created.run_id)
    completed = next(
        event for event in events if event.event_type == "thinking_summary_completed"
    )

    assert run is not None
    assert run.status == "completed"
    assert not [event for event in events if event.event_type == "thinking_summary_delta"]
    assert completed.payload["has_summary"] is False


def test_thinking_summary_unavailable_does_not_emit_fake_summary(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=RecordingFinalLlm(),
        default_model="main-model",
        enable_workstream_narrator=True,
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)

    events = store.list_events(created.run_id)
    completed = next(
        event for event in events if event.event_type == "thinking_summary_completed"
    )

    assert not [event for event in events if event.event_type == "thinking_summary_delta"]
    assert completed.payload["has_summary"] is False


def test_thinking_summary_rejects_unsupported_claims(tmp_path) -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="thinking_started",
        message="Klara is preparing the runtime loop.",
    )
    narrator = ThinkingSummaryNarrator(
        client=StaticNarratorLlm(
            json.dumps(
                {
                    "summary": "Klara searched the web and compared current sources.",
                    "evidence_event_ids": [event.event_id],
                    "confidence": 0.9,
                }
            )
        ),
        model="narrator-model",
        prompt_path=_prompt(tmp_path),
    )

    summary = narrator.create_summary(
        ThinkingSummaryInput(
            user_request="hello",
            selected_model="main-model",
            run_status="completed",
            duration_ms=10,
            events=(event,),
        )
    )

    assert summary is None


def _prompt(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return strict JSON.", encoding="utf-8")
    return prompt
