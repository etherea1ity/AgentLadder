from __future__ import annotations

import json
import time

from apps.api.schemas import RunEventRecord
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService, _narratable_activity_facts
from apps.api.services.sse_bus import SSEBus
from apps.api.services.workstream_narrator import (
    ThinkingActivityInput,
    ThinkingActivityNarrator,
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
        facts = payload["activity_facts"]
        first_fact = facts[0]
        first_evidence_id = first_fact["evidence_event_ids"][0]
        if first_fact["kind"] == "request_orientation":
            items = [
                {
                    "title": "Request understood",
                    "body": "Klara identified the request goal and prepared a concise response.",
                    "kind": "orientation",
                    "evidence_fact_ids": [first_fact["id"]],
                    "evidence_event_ids": [first_evidence_id],
                    "confidence": 0.82,
                }
            ]
        else:
            items = [
                {
                    "title": "Search result metadata received",
                    "body": "Klara received public source candidates from a tool step.",
                    "kind": "evidence",
                    "evidence_fact_ids": [first_fact["id"]],
                    "evidence_event_ids": [first_evidence_id],
                    "confidence": 0.82,
                }
            ]
        if len(facts) > 1:
            second_fact = facts[1]
            second_evidence_id = second_fact["evidence_event_ids"][0]
            items.append(
                {
                    "title": "Source material returned",
                    "body": "Klara received fetched source material for the selected result.",
                    "kind": "evidence",
                    "evidence_fact_ids": [second_fact["id"]],
                    "evidence_event_ids": [second_evidence_id],
                    "confidence": 0.78,
                }
            )
        return ModelResponse(
            content=json.dumps(
                {
                    "text": self.summary,
                    "items": items,
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


class ReasoningFinalLlm(RecordingFinalLlm):
    """Main model fixture that returns provider-visible reasoning metadata."""

    def complete(self, **kwargs: object) -> ModelResponse:
        self.calls.append(kwargs["messages"])  # type: ignore[index]
        return ModelResponse(
            content="final answer",
            reasoning_summary="The provider returned a safe summary of model thinking.",
            reasoning_source="message.reasoning_content",
        )


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


def test_provider_reasoning_delta_does_not_enter_assistant_content(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    main_llm = ReasoningFinalLlm()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=main_llm,
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)

    assistant = store.get_message(created.assistant_message_id)
    events = store.list_events(created.run_id)
    deltas = [event for event in events if event.event_type == "provider_reasoning_delta"]

    assert assistant is not None
    assert assistant.content == "final answer"
    assert deltas
    assert deltas[0].payload["items"][0]["source"] == "provider_reasoning"
    assert "safe summary" in deltas[0].payload["items"][0]["body"]
    assert "safe summary" not in assistant.content
    assert "safe summary" not in main_llm.calls[0][0].content


def test_plain_llm_run_with_narrator_emits_request_orientation_activity(tmp_path) -> None:
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
    completed = next(
        event for event in events if event.event_type == "thinking_summary_completed"
    )

    deltas = [event for event in events if event.event_type == "thinking_summary_delta"]
    assert deltas
    assert deltas[-1].payload["items"][0]["title"] == "Request understood"
    assert completed.payload["has_summary"] is True
    assert narrator.inputs
    assert [fact["kind"] for fact in narrator.inputs[-1]["activity_facts"]] == [
        "request_orientation"
    ]


def test_live_activity_narrator_emits_delta_from_meaningful_fact(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    narrator = SummaryNarratorLlm(
        "Klara summarized a live public tool step."
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
    run_id = "run-live-activity"
    stop, thread = service._start_live_activity_narrator(
        run_id=run_id,
        user_request="search recent news",
        selected_model="main-model",
        started=time.perf_counter(),
    )

    service._emit(
        run_id,
        "tool_call_completed",
        "web_search returned an observation.",
        {
            "tool_result": {
                "tool_call_id": "call-1",
                "name": "web_search",
                "ok": True,
                "structured_summary": {
                    "provider": "duckduckgo_lite",
                    "result_count": 5,
                    "truncated": False,
                },
            }
        },
    )
    try:
        for _ in range(30):
            if [
                event
                for event in store.list_events(run_id)
                if event.event_type == "thinking_summary_delta"
            ]:
                break
            time.sleep(0.1)
    finally:
        service._stop_live_activity_narrator(stop, thread)

    deltas = [
        event for event in store.list_events(run_id) if event.event_type == "thinking_summary_delta"
    ]

    assert deltas
    assert deltas[-1].payload["phase"] == "live"
    assert deltas[-1].payload["items"][0]["source"] == "narrator_model"
    assert narrator.inputs
    assert [fact["kind"] for fact in narrator.inputs[-1]["activity_facts"]] == [
        "web_search_result"
    ]
    assert not [event for event in store.list_events(run_id) if event.event_type == "workstream_note"]


def test_thinking_summary_uses_only_narratable_activity_facts(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    narrator = SummaryNarratorLlm(
        "Klara summarized the meaningful public tool activity."
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
    run_id = "run-with-tool-facts"
    plain_llm_fact = {
        "id": "fact_plain_llm",
        "kind": "llm_round",
        "status": "completed",
        "source_event_type": "llm_call_completed",
        "evidence_event_ids": ["evt_plain_llm"],
        "llm": {"tool_call_count": 0},
    }
    search_fact = {
        "id": "fact_search",
        "kind": "web_search_result",
        "status": "completed",
        "source_event_type": "tool_call_completed",
        "evidence_event_ids": ["evt_search"],
        "tool": {"name": "web_search", "ok": True},
    }
    fetch_fact = {
        "id": "fact_fetch",
        "kind": "web_fetch_result",
        "status": "completed",
        "source_event_type": "tool_call_completed",
        "evidence_event_ids": ["evt_fetch"],
        "tool": {"name": "web_fetch", "ok": True},
    }
    for fact in (plain_llm_fact, search_fact, fetch_fact):
        store.append_event(_activity_fact_record(run_id, fact))

    summary = service._create_thinking_summary(
        run_id=run_id,
        user_request="hello",
        selected_model="main-model",
        duration_ms=25,
    )

    assert summary is not None
    assert summary.summary == "Klara summarized the meaningful public tool activity."
    assert [fact["kind"] for fact in narrator.inputs[0]["activity_facts"]] == [
        "web_search_result",
        "web_fetch_result",
    ]


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
    assert "Search result metadata received" not in assistant.content
    assert "public trace" not in main_llm.calls[0][0].content
    assert "Search result metadata received" not in main_llm.calls[0][0].content


def test_activity_facts_do_not_enter_assistant_message_content(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    main_llm = RecordingFinalLlm()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=main_llm,
        default_model="main-model",
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)
    assistant = store.get_message(created.assistant_message_id)
    events = store.list_events(created.run_id)

    assert assistant is not None
    assert assistant.content == "final answer"
    assert [event for event in events if event.event_type == "activity_fact_recorded"]
    assert "Search result metadata received" not in assistant.content
    assert "Search result metadata received" not in main_llm.calls[0][0].content


def test_thinking_activity_narrator_failure_does_not_fail_run(tmp_path) -> None:
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
    assert [event for event in events if event.event_type == "narrator_failed"]


def test_invalid_narrator_json_emits_rejected_diagnostic(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    service = RunService(
        store=store,
        bus=SSEBus(),
        llm_client=RecordingFinalLlm(),
        default_model="main-model",
        narrator_client=StaticNarratorLlm("not json"),
        narrator_model="narrator-model",
        enable_workstream_narrator=True,
        trace_path=str(tmp_path / "trace.jsonl"),
    )

    created = service.create_run(session.session_id, "hello")
    service._threads[created.run_id].join(timeout=5)

    events = store.list_events(created.run_id)
    rejected = [event for event in events if event.event_type == "narrator_rejected"]

    assert rejected
    assert rejected[-1].payload["reason"] == "invalid_json"
    assert not [event for event in events if event.event_type == "thinking_summary_delta"]


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


def test_narratable_activity_facts_exclude_boilerplate_model_events() -> None:
    facts = (
        {"id": "fact_request", "kind": "request_orientation", "status": "completed"},
        {"id": "fact_started", "kind": "llm_round", "llm": {"tool_call_count": None}},
        {"id": "fact_answer", "kind": "answer_phase", "status": "started"},
        {"id": "fact_plain", "kind": "llm_round", "llm": {"tool_call_count": 0}},
        {"id": "fact_tool_model", "kind": "llm_round", "llm": {"tool_call_count": 1}},
        {"id": "fact_search", "kind": "web_search_result", "status": "completed"},
        {"id": "fact_fetch", "kind": "web_fetch_result", "status": "completed"},
    )

    filtered = _narratable_activity_facts(facts)

    assert [fact["id"] for fact in filtered] == [
        "fact_request",
        "fact_tool_model",
        "fact_search",
        "fact_fetch",
    ]


def test_thinking_summary_rejects_unsupported_claims(tmp_path) -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="thinking_started",
        message="Klara is preparing the runtime loop.",
    )
    fact_event = _fact_event(event, kind="llm_round")
    narrator = ThinkingActivityNarrator(
        client=StaticNarratorLlm(
            json.dumps(
                {
                    "text": "Klara searched the web and compared current sources.",
                    "items": [
                        {
                            "title": "Searched the web",
                            "body": "Klara searched the web and compared current sources.",
                            "kind": "evidence",
                            "evidence_fact_ids": [fact_event.payload["fact"]["id"]],
                            "evidence_event_ids": [event.event_id],
                            "confidence": 0.9,
                        },
                        {
                            "title": "Writing the answer",
                            "body": "Klara prepared the final response.",
                            "kind": "composition",
                            "evidence_fact_ids": [fact_event.payload["fact"]["id"]],
                            "evidence_event_ids": [event.event_id],
                            "confidence": 0.6,
                        },
                    ],
                }
            )
        ),
        model="narrator-model",
        prompt_path=_prompt(tmp_path),
    )

    summary = narrator.create_summary(
        ThinkingActivityInput(
            user_request="hello",
            selected_model="main-model",
            run_status="completed",
            duration_ms=10,
            events=(event, fact_event),
            activity_facts=(fact_event.payload["fact"],),
        )
    )

    assert summary is None


def test_thinking_summary_rejects_unknown_evidence_ids(tmp_path) -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="thinking_started",
        message="Klara is preparing the runtime loop.",
    )
    fact_event = _fact_event(event, kind="llm_round")
    narrator = ThinkingActivityNarrator(
        client=StaticNarratorLlm(
            json.dumps(
                {
                    "text": "Klara summarized the public runtime events.",
                    "items": [
                        {
                            "title": "Preparing the run",
                            "body": "Klara set up the runtime for this request.",
                            "kind": "orientation",
                            "evidence_fact_ids": [fact_event.payload["fact"]["id"]],
                            "evidence_event_ids": [event.event_id],
                            "confidence": 0.8,
                        },
                        {
                            "title": "Writing the answer",
                            "body": "Klara prepared the final response.",
                            "kind": "composition",
                            "evidence_fact_ids": ["fact_missing"],
                            "evidence_event_ids": ["evt_missing"],
                            "confidence": 0.7,
                        },
                    ],
                }
            )
        ),
        model="narrator-model",
        prompt_path=_prompt(tmp_path),
    )

    summary = narrator.create_summary(
        ThinkingActivityInput(
            user_request="hello",
            selected_model="main-model",
            run_status="completed",
            duration_ms=10,
            events=(event, fact_event),
            activity_facts=(fact_event.payload["fact"],),
        )
    )

    assert summary is None


def test_thinking_summary_rejects_public_reasoning_wording(tmp_path) -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="llm_call_completed",
        message="Model response received.",
    )
    fact_event = _fact_event(event, kind="llm_round")
    fact_id = fact_event.payload["fact"]["id"]
    narrator = ThinkingActivityNarrator(
        client=StaticNarratorLlm(
            json.dumps(
                {
                    "text": "Klara summarized the public runtime events.",
                    "items": [
                        {
                            "title": "Completed LLM reasoning round",
                            "body": "The model reasoning round concluded successfully.",
                            "kind": "orientation",
                            "evidence_fact_ids": [fact_id],
                            "evidence_event_ids": [event.event_id],
                            "confidence": 0.8,
                        },
                        {
                            "title": "Writing the answer",
                            "body": "Klara prepared the final response.",
                            "kind": "composition",
                            "evidence_fact_ids": [fact_id],
                            "evidence_event_ids": [event.event_id],
                            "confidence": 0.7,
                        },
                    ],
                }
            )
        ),
        model="narrator-model",
        prompt_path=_prompt(tmp_path),
    )

    summary = narrator.create_summary(
        ThinkingActivityInput(
            user_request="hello",
            selected_model="main-model",
            run_status="completed",
            duration_ms=10,
            events=(event, fact_event),
            activity_facts=(fact_event.payload["fact"],),
        )
    )

    assert summary is None


def test_thinking_summary_rejects_raw_tool_detail_wording(tmp_path) -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="tool_call_completed",
        message="web_search returned an observation.",
    )
    fact_event = _fact_event(event, kind="web_search_result")
    fact_id = fact_event.payload["fact"]["id"]
    narrator = ThinkingActivityNarrator(
        client=StaticNarratorLlm(
            json.dumps(
                {
                    "text": "Klara summarized public tool activity.",
                    "items": [
                        {
                            "title": "Search results returned",
                            "body": "Klara used the query 'world cup latest' to search public sources.",
                            "kind": "evidence",
                            "evidence_fact_ids": [fact_id],
                            "evidence_event_ids": [event.event_id],
                            "confidence": 0.8,
                        },
                        {
                            "title": "Search metadata returned",
                            "body": "Klara received search result metadata from the tool.",
                            "kind": "evidence",
                            "evidence_fact_ids": [fact_id],
                            "evidence_event_ids": [event.event_id],
                            "confidence": 0.7,
                        },
                    ],
                }
            )
        ),
        model="narrator-model",
        prompt_path=_prompt(tmp_path),
    )

    summary = narrator.create_summary(
        ThinkingActivityInput(
            user_request="hello",
            selected_model="main-model",
            run_status="completed",
            duration_ms=10,
            events=(event, fact_event),
            activity_facts=(fact_event.payload["fact"],),
        )
    )

    assert summary is None


def test_thinking_summary_rejects_chinese_thinking_wording(tmp_path) -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="llm_call_completed",
        message="Model response received.",
    )
    fact_event = _fact_event(event, kind="llm_round")
    fact_id = fact_event.payload["fact"]["id"]
    narrator = ThinkingActivityNarrator(
        client=StaticNarratorLlm(
            json.dumps(
                {
                    "text": "Klara summarized the public runtime events.",
                    "items": [
                        {
                            "title": "\u542f\u52a8 LLM \u601d\u8003\u6d41\u7a0b",
                            "body": "\u7cfb\u7edf\u542f\u52a8\u4e86 LLM \u601d\u8003\u6d41\u7a0b\u3002",
                            "kind": "orientation",
                            "evidence_fact_ids": [fact_id],
                            "evidence_event_ids": [event.event_id],
                            "confidence": 0.8,
                        },
                        {
                            "title": "\u51c6\u5907\u56de\u7b54",
                            "body": "Klara \u51c6\u5907\u8f93\u51fa\u6700\u7ec8\u56de\u7b54\u3002",
                            "kind": "composition",
                            "evidence_fact_ids": [fact_id],
                            "evidence_event_ids": [event.event_id],
                            "confidence": 0.7,
                        },
                    ],
                },
                ensure_ascii=False,
            )
        ),
        model="narrator-model",
        prompt_path=_prompt(tmp_path),
    )

    summary = narrator.create_summary(
        ThinkingActivityInput(
            user_request="hello",
            selected_model="main-model",
            run_status="completed",
            duration_ms=10,
            events=(event, fact_event),
            activity_facts=(fact_event.payload["fact"],),
        )
    )

    assert summary is None

def _prompt(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return strict JSON.", encoding="utf-8")
    return prompt


def _fact_event(event: RunEventRecord, *, kind: str) -> RunEventRecord:
    return RunEventRecord(
        run_id=event.run_id,
        event_type="activity_fact_recorded",
        message="Activity fact recorded.",
        payload={
            "fact": {
                "id": f"fact_{event.event_id}",
                "kind": kind,
                "status": "completed",
                "source_event_type": event.event_type,
                "evidence_event_ids": [event.event_id],
            }
        },
    )


def _activity_fact_record(run_id: str, fact: dict[str, object]) -> RunEventRecord:
    return RunEventRecord(
        run_id=run_id,
        event_type="activity_fact_recorded",
        message="Activity fact recorded.",
        payload={"fact": fact},
    )
