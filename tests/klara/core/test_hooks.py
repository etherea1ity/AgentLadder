from __future__ import annotations

import json

from klara.core.events import EventKind, KlaraEvent
from klara.core.hooks import HookManager, JsonlTraceHook
from klara.core.loop import KlaraLoop
from klara.core.messages import ModelResponse
from klara.tools.executor import ToolExecutor


class FinalLlm:
    """Fake LLM that always returns a final answer."""

    def complete(self, **kwargs: object) -> ModelResponse:
        """Return a deterministic response for hook tests."""

        return ModelResponse(content="done")


class BrokenHook:
    """Hook that fails so tests can verify failure isolation."""

    def on_event(self, event: KlaraEvent) -> None:
        """Raise for every event."""

        raise RuntimeError("hook broke")


class RecordingHook:
    """Hook that records lifecycle events for assertions."""

    def __init__(self) -> None:
        """Create an empty event list."""

        self.events: list[KlaraEvent] = []

    def on_event(self, event: KlaraEvent) -> None:
        """Remember one emitted event."""

        self.events.append(event)


def test_hook_failure_does_not_crash_run() -> None:
    hooks = HookManager([BrokenHook()])
    loop = KlaraLoop(llm=FinalLlm(), tool_executor=ToolExecutor(), hooks=hooks)

    result = loop.run("hi", run_id="run-hook-failure")

    assert result.final_answer == "done"
    assert result.hook_failures
    assert result.hook_failures[0][0] == "run.started"


def test_event_seq_is_monotonic_per_run() -> None:
    recorder = RecordingHook()
    hooks = HookManager([recorder])
    loop = KlaraLoop(llm=FinalLlm(), tool_executor=ToolExecutor(), hooks=hooks)

    loop.run("hi", run_id="run-seq")

    assert [event.seq for event in recorder.events] == list(
        range(1, len(recorder.events) + 1)
    )


def test_event_id_is_unique() -> None:
    recorder = RecordingHook()
    hooks = HookManager([recorder])
    loop = KlaraLoop(llm=FinalLlm(), tool_executor=ToolExecutor(), hooks=hooks)

    loop.run("hi", run_id="run-event-id")

    event_ids = [event.event_id for event in recorder.events]
    assert len(event_ids) == len(set(event_ids))


def test_jsonl_trace_hook_writes_public_events(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    hooks = HookManager([JsonlTraceHook(trace_path)])
    loop = KlaraLoop(llm=FinalLlm(), tool_executor=ToolExecutor(), hooks=hooks)

    loop.run("hi", run_id="run-trace")

    # Parse every trace line so assertions use the same public JSONL contract.
    events = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    event_types = [event["type"] for event in events]
    assert event_types == [
        "run.started",
        "turn.started",
        "llm.started",
        "llm.completed",
        "turn.completed",
        "run.completed",
    ]
    assert all(event["schema_version"] == 1 for event in events)
    assert all(event["run_id"] == "run-trace" for event in events)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["event_id"].startswith("evt_") for event in events)


def test_jsonl_trace_hook_writes_event_id_and_seq(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    event = KlaraEvent(
        type=EventKind.RUN_STARTED,
        run_id="run-direct-trace",
        payload={"model": "fake-model"},
        event_id="evt_test",
        seq=7,
    )
    JsonlTraceHook(trace_path).on_event(event)

    record = json.loads(trace_path.read_text(encoding="utf-8"))

    assert record["event_id"] == "evt_test"
    assert record["seq"] == 7


def test_public_event_does_not_include_private_payload_content() -> None:
    event = KlaraEvent(
        type=EventKind.RUN_STARTED,
        run_id="run-public-boundary",
        payload={"private_note": "raw hidden scratchpad"},
        public_payload={"model": "fake-model"},
        private_payload_ref="private://run-public-boundary/1",
    )

    public = event.to_public_dict()
    serialized = json.dumps(public)

    assert public["payload"] == {"model": "fake-model"}
    assert public["private_payload_ref"] == "private://run-public-boundary/1"
    assert "raw hidden scratchpad" not in serialized
