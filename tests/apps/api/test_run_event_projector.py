from __future__ import annotations

import json

from apps.api.services.run_event_projector import RunEventProjector
from klara.core.events import KlaraEvent


def test_llm_started_projection_includes_model_and_finalization() -> None:
    projector = RunEventProjector(selected_model="fallback-model")
    event = KlaraEvent(
        type="llm.started",
        run_id="run-1",
        payload={"turn_index": 2, "model": "selected-model", "finalization": True},
    )

    projected = projector.project(event)

    assert len(projected) == 1
    assert projected[0].event_type == "llm_call_started"
    assert projected[0].payload == {
        "turn_index": 2,
        "model": "selected-model",
        "finalization": True,
    }


def test_llm_completed_projection_updates_usage_totals() -> None:
    projector = RunEventProjector()
    event = KlaraEvent(
        type="llm.completed",
        run_id="run-1",
        payload={
            "turn_index": 1,
            "tool_call_count": 0,
            "usage": {"input_tokens": 3, "output_tokens": 5},
        },
    )

    projected = projector.project(event)

    assert projected[0].event_type == "llm_call_completed"
    assert projected[0].payload["prompt_tokens"] == 3
    assert projected[0].payload["completion_tokens"] == 5
    assert projected[0].payload["total_tokens"] == 8
    assert projector.usage_totals.has_reported is True
    assert projector.usage_totals.total_tokens == 8


def test_tool_events_project_to_visible_started_completed_and_failed() -> None:
    projector = RunEventProjector()

    started = projector.project(
        KlaraEvent(
            type="tool.started",
            run_id="run-1",
            payload={
                "turn_index": 1,
                "tool_call": {"id": "call-1", "name": "current_time"},
            },
        )
    )[0]
    completed = projector.project(
        KlaraEvent(
            type="tool.completed",
            run_id="run-1",
            payload={
                "turn_index": 1,
                "tool_result": {
                    "tool_call_id": "call-1",
                    "name": "current_time",
                    "content": "full tool content should stay out of API projection",
                    "content_preview": "2026-06-18",
                    "content_length": 10,
                    "ok": True,
                },
            },
        )
    )[0]
    failed = projector.project(
        KlaraEvent(
            type="tool.failed",
            run_id="run-1",
            payload={
                "turn_index": 1,
                "blocked": True,
                "tool_result": {
                    "tool_call_id": "call-2",
                    "name": "web_search",
                    "content": "hidden raw content",
                    "content_preview": "",
                    "content_length": 0,
                    "ok": False,
                    "error": "Tool blocked by hook: test",
                },
            },
        )
    )[0]

    assert started.event_type == "tool_call_started"
    assert started.payload["tool_call"]["name"] == "current_time"
    assert completed.event_type == "tool_call_completed"
    assert completed.payload["tool_result"]["content_preview"] == "2026-06-18"
    assert "content" not in completed.payload["tool_result"]
    assert failed.event_type == "tool_call_failed"
    assert failed.payload["blocked"] is True
    assert failed.payload["tool_result"]["error"] == "Tool blocked by hook: test"
    assert "content" not in failed.payload["tool_result"]


def test_policy_and_hook_events_project_to_visible_runtime_events() -> None:
    projector = RunEventProjector()

    policy = projector.project(
        KlaraEvent(
            type="tool_policy.stopped",
            run_id="run-1",
            payload={
                "turn_index": 2,
                "stop_reason": "max_tool_calls",
                "reason": "The tool call budget has been reached.",
            },
        )
    )[0]
    hook = projector.project(
        KlaraEvent(
            type="pre_tool_use.completed",
            run_id="run-1",
            payload={
                "turn_index": 1,
                "allowed": False,
                "reason": "blocked for test",
            },
        )
    )[0]

    assert policy.event_type == "policy_stop"
    assert policy.payload["stop_reason"] == "max_tool_calls"
    assert hook.event_type == "hook_placement_completed"
    assert hook.payload["placement"] == "PreToolUse"
    assert hook.payload["allowed"] is False
    assert hook.payload["reason"] == "blocked for test"


def test_projector_does_not_expose_raw_answer_delta_or_chain_of_thought() -> None:
    projector = RunEventProjector()
    event = KlaraEvent(
        type="llm.completed",
        run_id="run-1",
        payload={
            "turn_index": 1,
            "tool_call_count": 0,
            "answer_delta": "secret delta",
            "raw_chain_of_thought": "hidden scratchpad",
            "usage": {},
        },
    )

    projected = projector.project(event)
    serialized = json.dumps([item.payload for item in projected])

    assert "secret delta" not in serialized
    assert "hidden scratchpad" not in serialized
    assert projector.project(
        KlaraEvent(type="run.completed", run_id="run-1", payload={})
    ) == ()
