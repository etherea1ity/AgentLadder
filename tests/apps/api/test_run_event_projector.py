from __future__ import annotations

import json

from apps.api.schemas import RunEventRecord
from apps.api.services.run_event_projector import RunEventProjector, project_activity_item
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


def test_llm_completed_projection_includes_duration_and_usage() -> None:
    projector = RunEventProjector()
    event = KlaraEvent(
        type="llm.completed",
        run_id="run-1",
        payload={
            "turn_index": 1,
            "tool_call_count": 0,
            "usage": {
                "prompt_tokens": 7,
                "completion_tokens": 11,
                "total_tokens": 18,
            },
            "metrics": {
                "duration_ms": 123,
                "prompt_tokens": 7,
                "completion_tokens": 11,
                "total_tokens": 18,
                "token_source": "reported",
            },
        },
    )

    projected = projector.project(event)[0]

    assert projected.event_type == "llm_call_completed"
    assert projected.payload["duration_ms"] == 123
    assert projected.payload["latency_ms"] == 123
    assert projected.payload["prompt_tokens"] == 7
    assert projected.payload["completion_tokens"] == 11
    assert projected.payload["total_tokens"] == 18
    assert projected.payload["token_source"] == "reported"


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


def test_tool_completed_projection_includes_duration() -> None:
    projector = RunEventProjector()
    event = KlaraEvent(
        type="tool.completed",
        run_id="run-1",
        payload={
            "turn_index": 1,
            "tool_result": {
                "tool_call_id": "call-1",
                "name": "current_time",
                "content_preview": "2026-06-18",
                "content_length": 10,
                "ok": True,
            },
            "metrics": {"duration_ms": 42},
        },
    )

    projected = projector.project(event)[0]

    assert projected.event_type == "tool_call_completed"
    assert projected.payload["duration_ms"] == 42
    assert projected.payload["latency_ms"] == 42
    assert projected.payload["metrics"]["duration_ms"] == 42


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


def test_llm_call_started_run_event_projects_activity_item() -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="llm_call_started",
        message="Klara is calling the model.",
        payload={"model": "qwen/qwen-flash"},
    )

    projected = project_activity_item(event)

    assert projected is not None
    assert projected.event_type == "activity_item_upserted"
    item = projected.payload["item"]
    assert item["title"] == "Reading the request"
    assert item["source"] == "runtime_event"
    assert item["evidence_event_ids"] == [event.event_id]


def test_web_search_activity_item_is_sanitized() -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="tool_call_started",
        message="Klara is using web_search.",
        payload={
            "tool_call": {
                "id": "call-1",
                "name": "web_search",
                "arguments": {"query": "private raw query"},
            }
        },
    )

    projected = project_activity_item(event)

    assert projected is not None
    item = projected.payload["item"]
    serialized = json.dumps(item, ensure_ascii=False)
    assert item["kind"] == "evidence"
    assert item["status"] == "running"
    assert item["evidence_event_ids"] == [event.event_id]
    assert "private raw query" not in serialized


def test_web_fetch_completed_activity_item_is_completed_and_sanitized() -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="tool_call_completed",
        message="web_fetch returned an observation.",
        payload={
            "tool_result": {
                "tool_call_id": "call-1",
                "name": "web_fetch",
                "content_preview": "safe preview",
                "url": "https://example.com/full/path",
            }
        },
    )

    projected = project_activity_item(event)

    assert projected is not None
    item = projected.payload["item"]
    serialized = json.dumps(item, ensure_ascii=False)
    assert item["title"] == "Source material reviewed"
    assert item["status"] == "completed"
    assert item["evidence_event_ids"] == [event.event_id]
    assert "https://example.com" not in serialized
