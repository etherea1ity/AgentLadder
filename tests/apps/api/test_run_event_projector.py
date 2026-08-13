from __future__ import annotations

import json

from apps.api.schemas import RunEventRecord
from apps.api.services.run_event_projector import (
    RunEventProjector,
    project_assistant_activity,
    project_activity_fact,
    project_provider_reasoning,
)
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


def test_provider_fallback_and_prompt_recovery_events_are_projected() -> None:
    """Public recovery events should survive the API/SSE projection unchanged."""

    projector = RunEventProjector(selected_model="primary/model")
    fallback = projector.project(
        KlaraEvent(
            type="model_route.fallback_started",
            run_id="run-recovery",
            payload={
                "failed_model": "primary/model",
                "fallback_model": "fallback/model",
                "reason": "provider_unavailable",
            },
        )
    )
    recovered = projector.project(
        KlaraEvent(
            type="prompt_recovery.completed",
            run_id="run-recovery",
            payload={"attempt": 1, "messages_before": 12, "messages_after": 5},
        )
    )

    assert fallback[0].event_type == "model_route.fallback_started"
    assert fallback[0].payload["fallback_model"] == "fallback/model"
    assert recovered[0].event_type == "prompt_recovery.completed"
    assert recovered[0].payload["messages_after"] == 5


def test_llm_completion_projects_requested_and_actual_model() -> None:
    projector = RunEventProjector(selected_model="primary/model")
    projected = projector.project(
        KlaraEvent(
            type="llm.completed",
            run_id="run-route",
            payload={
                "requested_model": "primary/model",
                "model": "fallback/model",
                "usage": {},
                "metrics": {},
            },
        )
    )

    assert projected[0].payload["requested_model"] == "primary/model"
    assert projected[0].payload["model"] == "fallback/model"


def test_llm_started_projection_preserves_input_profile() -> None:
    projector = RunEventProjector()
    input_profile = {
        "message_count": 3,
        "role_counts": {"user": 2, "assistant": 1},
        "system_prompt_hash": "abc123def4567890",
        "tool_spec_count": 2,
        "tool_names": ["web_search", "update_activity"],
    }
    event = KlaraEvent(
        type="llm.started",
        run_id="run-1",
        payload={
            "turn_index": 1,
            "model": "selected-model",
            "input_profile": input_profile,
        },
    )

    projected = projector.project(event)[0]

    assert projected.event_type == "llm_call_started"
    assert projected.payload["input_profile"] == input_profile


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


def test_llm_completed_projection_preserves_response_profile() -> None:
    projector = RunEventProjector()
    response_profile = {
        "content_chars": 14,
        "has_content": True,
        "external_tool_call_count": 1,
        "tool_call_names": ["web_fetch"],
        "has_activity_commentary": True,
    }
    event = KlaraEvent(
        type="llm.completed",
        run_id="run-1",
        payload={
            "turn_index": 1,
            "tool_call_count": 1,
            "usage": {},
            "response_profile": response_profile,
        },
    )

    projected = projector.project(event)[0]

    assert projected.event_type == "llm_call_completed"
    assert projected.payload["response_profile"] == response_profile


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


def test_llm_completed_projection_preserves_public_activity_metadata() -> None:
    projector = RunEventProjector()
    event = KlaraEvent(
        type="llm.completed",
        run_id="run-1",
        payload={
            "turn_index": 1,
            "tool_call_count": 1,
            "activity_commentary": {
                "text": "I will check public sources first.",
                "source": "assistant.content_with_tool_calls",
                "phase": "before_tool",
            },
            "usage": {},
        },
    )

    projected = projector.project(event)[0]

    assert projected.event_type == "llm_call_completed"
    assert projected.payload["activity_commentary"] == {
        "text": "I will check public sources first.",
        "source": "assistant.content_with_tool_calls",
        "phase": "before_tool",
    }


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


def test_policy_and_hook_events_project_to_visible_run_events() -> None:
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


def test_web_tool_started_projects_specific_web_event() -> None:
    projector = RunEventProjector()

    projected = projector.project(
        KlaraEvent(
            type="tool.started",
            run_id="run-1",
            payload={
                "turn_index": 1,
                "tool_call": {
                    "id": "call-search",
                    "name": "web_search",
                    "arguments": {"query": "private query"},
                },
                "started_at": "2026-06-23T00:00:00Z",
            },
        )
    )

    assert [event.event_type for event in projected] == [
        "tool_call_started",
        "web_search.started",
    ]
    assert projected[1].payload == {
        "turn_index": 1,
        "tool_call_id": "call-search",
        "started_at": "2026-06-23T00:00:00Z",
    }


def test_web_research_controller_events_project_to_run_events() -> None:
    projector = RunEventProjector()

    projected = projector.project(
        KlaraEvent(
            type="evidence.readiness_evaluated",
            run_id="run-1",
            payload={
                "ready": False,
                "status": "need_more_fetch",
                "decision_reason": "no_fetched_sources",
                "gaps": ["Need at least one fetched source before answering."],
            },
        )
    )

    assert len(projected) == 1
    assert projected[0].event_type == "evidence.readiness_evaluated"
    assert projected[0].payload["ready"] is False
    assert projected[0].payload["decision_reason"] == "no_fetched_sources"


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


def test_llm_call_started_run_event_projects_activity_fact() -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="llm_call_started",
        message="Klara is calling the model.",
        payload={
            "model": "qwen/qwen-flash",
            "input_profile": {
                "message_count": 1,
                "system_prompt_hash": "abc123def4567890",
            },
        },
    )

    projected = project_activity_fact(event)

    assert projected is not None
    assert projected.event_type == "activity_fact_recorded"
    fact = projected.payload["fact"]
    assert fact["kind"] == "llm_round"
    assert fact["status"] == "started"
    assert fact["llm"]["model"] == "qwen/qwen-flash"
    assert fact["llm"]["input_profile"]["message_count"] == 1
    assert fact["llm"]["input_profile"]["system_prompt_hash"] == "abc123def4567890"
    assert fact["evidence_event_ids"] == [event.event_id]
    assert "title" not in fact
    assert "body" not in fact


def test_web_search_activity_fact_is_sanitized() -> None:
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

    projected = project_activity_fact(event)

    assert projected is not None
    fact = projected.payload["fact"]
    serialized = json.dumps(fact, ensure_ascii=False)
    assert fact["kind"] == "tool_call"
    assert fact["status"] == "started"
    assert fact["tool"]["name"] == "web_search"
    assert fact["evidence_event_ids"] == [event.event_id]
    assert "private raw query" not in serialized
    assert "title" not in fact
    assert "body" not in fact


def test_web_fetch_completed_activity_fact_is_completed_and_sanitized() -> None:
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

    projected = project_activity_fact(event)

    assert projected is not None
    fact = projected.payload["fact"]
    serialized = json.dumps(fact, ensure_ascii=False)
    assert fact["kind"] == "web_fetch_result"
    assert fact["status"] == "completed"
    assert fact["evidence_event_ids"] == [event.event_id]
    assert "https://example.com" not in serialized
    assert "title" not in fact
    assert "body" not in fact


def test_web_search_completed_activity_fact_does_not_expose_query_preview() -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="tool_call_completed",
        message="web_search returned an observation.",
        payload={
            "tool_result": {
                "tool_call_id": "call-1",
                "name": "web_search",
                "content_preview": '{"query": "private raw query", "results": []}',
                "content_length": 120,
                "ok": True,
                "structured_summary": {
                    "provider": "duckduckgo_lite",
                    "result_count": 8,
                    "truncated": False,
                    "evidence_status": "candidate_snippets_only",
                },
            }
        },
    )

    projected = project_activity_fact(event)

    assert projected is not None
    fact = projected.payload["fact"]
    serialized = json.dumps(fact, ensure_ascii=False)
    assert fact["kind"] == "web_search_result"
    assert fact["web"]["result_count"] == 8
    assert "private raw query" not in serialized
    assert "observation_preview" not in fact
    assert "title" not in fact
    assert "body" not in fact


def test_thinking_summary_started_projects_request_orientation_fact() -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="thinking_summary_started",
        message="Klara is thinking.",
        payload={
            "request": {
                "preview": "\u8bf7\u5e2e\u6211\u5904\u7406 token=secret-value https://example.com/raw " + "x" * 160,
                "language": "zh",
            }
        },
    )

    projected = project_activity_fact(event)

    assert projected is not None
    fact = projected.payload["fact"]
    serialized = json.dumps(fact, ensure_ascii=False)
    assert fact["kind"] == "request_orientation"
    assert fact["status"] == "completed"
    assert fact["request"]["language"] == "zh"
    assert len(fact["request"]["preview"]) <= 120
    assert "secret-value" not in serialized
    assert "https://example.com" not in serialized
    assert "title" not in fact
    assert "body" not in fact


def test_provider_reasoning_projects_delta_and_completed_events() -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="llm_call_completed",
        message="Model call completed.",
        payload={
            "reasoning": {
                "source": "message.reasoning_content",
                "summary": "I considered the request shape before answering.",
            }
        },
    )

    projected = project_provider_reasoning(event)

    assert [item.event_type for item in projected] == [
        "provider_reasoning_delta",
        "provider_reasoning_completed",
    ]
    item = projected[0].payload["items"][0]
    assert item["source"] == "provider_reasoning"
    assert item["body"] == "I considered the request shape before answering."
    assert item["evidence_event_ids"] == [event.event_id]


def test_assistant_activity_projects_delta_and_completed_events() -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="llm_call_completed",
        message="Model call completed.",
        payload={
            "activity_commentary": {
                "text": "update_activity.text: I will check public sources first.",
                "source": "assistant.content_with_tool_calls",
                "phase": "before_tool",
            }
        },
    )

    projected = project_assistant_activity(event)

    assert [item.event_type for item in projected] == [
        "assistant_activity_delta",
        "assistant_activity_completed",
    ]
    assert projected[0].payload == {
        "activity_id": "activity_" + event.event_id,
        "sequence": None,
        "status": "completed",
        "text": "I will check public sources first.",
        "source": "main_model_commentary",
        "source_detail": "assistant.content_with_tool_calls",
        "phase": "before_tool",
        "evidence_event_ids": [event.event_id],
    }


def test_assistant_activity_projection_redacts_urls_and_rejects_raw_reasoning() -> None:
    event = RunEventRecord(
        run_id="run-1",
        event_type="llm_call_completed",
        message="Model call completed.",
        payload={
            "activity_commentary": {
                "text": "I will use https://example.com and token=secret.",
                "phase": "between_tools",
            }
        },
    )
    rejected = RunEventRecord(
        run_id="run-1",
        event_type="llm_call_completed",
        message="Model call completed.",
        payload={
            "activity_commentary": {
                "text": "My hidden chain-of-thought is private.",
            }
        },
    )

    projected = project_assistant_activity(event)

    assert "[url]" in projected[0].payload["text"]
    assert "https://example.com" not in projected[0].payload["text"]
    assert "token=secret" not in projected[0].payload["text"]
    assert project_assistant_activity(rejected) == ()
