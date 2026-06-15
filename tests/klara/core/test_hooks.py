from __future__ import annotations

import json

from klara.core.events import KlaraEvent
from klara.core.hooks import HookManager, JsonlTraceHook
from klara.core.loop import KlaraLoop
from klara.core.messages import ModelResponse
from klara.core.tool_executor import ToolExecutor


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


def test_hook_failure_does_not_crash_run() -> None:
    hooks = HookManager([BrokenHook()])
    loop = KlaraLoop(llm=FinalLlm(), tool_executor=ToolExecutor(), hooks=hooks)

    result = loop.run("hi", run_id="run-hook-failure")

    assert result.final_answer == "done"
    assert result.hook_failures
    assert result.hook_failures[0][0] == "run.started"


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
