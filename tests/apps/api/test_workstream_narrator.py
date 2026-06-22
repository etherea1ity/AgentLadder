from __future__ import annotations

import json

from apps.api.schemas import RunEventRecord
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from apps.api.services.workstream_narrator import (
    WorkstreamNarrator,
    WorkstreamNarratorInput,
)
from klara.core.messages import KlaraMessage, ModelResponse


class RecordingFinalLlm:
    """Main model fixture that records its model-visible messages."""

    def __init__(self) -> None:
        self.calls: list[tuple[KlaraMessage, ...]] = []

    def complete(self, **kwargs: object) -> ModelResponse:
        self.calls.append(kwargs["messages"])  # type: ignore[index]
        return ModelResponse(content="final answer")


class JsonNarratorLlm:
    """Narrator fixture that returns JSON using the first evidence event id."""

    def __init__(self, text: str = "Klara is preparing the runtime.") -> None:
        self.text = text

    def complete(self, **kwargs: object) -> ModelResponse:
        messages = kwargs["messages"]  # type: ignore[index]
        payload = json.loads(messages[0].content)
        evidence_id = payload["recent_events"][0]["event_id"]
        return ModelResponse(
            content=json.dumps(
                {
                    "emit": True,
                    "text": self.text,
                    "evidence_event_ids": [evidence_id],
                    "confidence": 0.8,
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


def test_narrator_emits_workstream_note_from_fake_model(tmp_path) -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="thinking_started",
        message="Klara is preparing the runtime loop.",
    )
    narrator = WorkstreamNarrator(
        client=JsonNarratorLlm("Klara is setting up the run."),
        model="narrator-model",
        prompt_path=_prompt(tmp_path),
    )

    note = narrator.create_note(
        WorkstreamNarratorInput(
            user_request="hello",
            selected_model="main-model",
            run_status="thinking",
            phase="thinking",
            elapsed_ms=10,
            recent_events=(event,),
        )
    )

    assert note is not None
    assert note.text == "Klara is setting up the run."
    assert note.evidence_event_ids == (event.event_id,)


def test_narrator_invalid_json_is_ignored(tmp_path) -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="thinking_started",
        message="Klara is preparing the runtime loop.",
    )
    narrator = WorkstreamNarrator(
        client=StaticNarratorLlm("not json"),
        model="narrator-model",
        prompt_path=_prompt(tmp_path),
    )

    note = narrator.create_note(
        WorkstreamNarratorInput(
            user_request="hello",
            selected_model="main-model",
            run_status="thinking",
            phase="thinking",
            elapsed_ms=10,
            recent_events=(event,),
        )
    )

    assert note is None


def test_narrator_unsupported_claims_are_rejected(tmp_path) -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="thinking_started",
        message="Klara is preparing the runtime loop.",
    )
    narrator = WorkstreamNarrator(
        client=StaticNarratorLlm(
            json.dumps(
                {
                    "emit": True,
                    "text": "Klara searched the web and found evidence.",
                    "evidence_event_ids": [event.event_id],
                    "confidence": 0.9,
                }
            )
        ),
        model="narrator-model",
        prompt_path=_prompt(tmp_path),
    )

    note = narrator.create_note(
        WorkstreamNarratorInput(
            user_request="hello",
            selected_model="main-model",
            run_status="thinking",
            phase="thinking",
            elapsed_ms=10,
            recent_events=(event,),
        )
    )

    assert note is None


def test_run_service_no_longer_emits_periodic_workstream_note(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    main_llm = RecordingFinalLlm()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=main_llm,
        default_model="main-model",
        narrator_client=JsonNarratorLlm("Klara is preparing the runtime."),
        narrator_model="narrator-model",
        enable_workstream_narrator=True,
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)

    events = store.list_events(created.run_id)
    answer_delta = next(event for event in events if event.event_type == "answer_delta")
    assistant = store.get_message(created.assistant_message_id)

    assert not [event for event in events if event.event_type == "workstream_note"]
    assert any(event.event_type == "thinking_summary_completed" for event in events)
    assert assistant is not None
    assert assistant.content == "final answer"
    assert "Klara is preparing the runtime." not in main_llm.calls[0][0].content
    assert events.index(
        next(event for event in events if event.event_type == "thinking_summary_completed")
    ) < events.index(answer_delta)


def test_narrator_failure_does_not_fail_run(tmp_path) -> None:
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

    assert run is not None
    assert run.status == "completed"
    assert not [event for event in events if event.event_type == "workstream_note"]


def _prompt(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return strict JSON.", encoding="utf-8")
    return prompt
