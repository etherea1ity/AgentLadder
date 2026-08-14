from __future__ import annotations

import json

from klara.core.messages import ModelResponse
from klara.core.tools import ToolCall
from klara.eval.agentbench_live import (
    DBBENCH_DECISION_GUARD,
    _agentbench_tools,
    _response_to_agentbench,
    _semantic_preflight,
    _validate_tool_call,
    render_agentbench_markdown,
)


RAW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "Execute SQL.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }
]


def test_agentbench_tool_schema_and_call_validation_are_exact() -> None:
    tool = _agentbench_tools(RAW_TOOLS)[0]
    valid = ToolCall("call-1", "execute_sql", {"query": "SELECT 1"})
    invalid = ToolCall("call-2", "execute_sql", {"sql": "SELECT 1"})
    assert tool.input_schema["additionalProperties"] is False
    assert _validate_tool_call(valid, {tool.name: tool.input_schema}) == (True, None)
    assert _validate_tool_call(invalid, {tool.name: tool.input_schema})[0] is False


def test_agentbench_wire_message_contains_no_text_when_calling_tool() -> None:
    response = ModelResponse(
        content="private-looking commentary",
        tool_calls=(ToolCall("call-1", "execute_sql", {"query": "SELECT 1"}),),
    )
    message = _response_to_agentbench(response)
    assert message["content"] is None
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
        "query": "SELECT 1"
    }


def test_agentbench_report_discloses_subset_boundary() -> None:
    report = {
        "passed": True,
        "candidate": {"model": "deepseek/deepseek-v4-flash"},
        "metrics": {
            "tasks_passed": 1,
            "tasks_total": 1,
            "candidate_controllable_success_rate": 1.0,
            "benchmark_artifact_count": 0,
            "invalid_tool_call_ratio": 0.0,
            "semantic_preflight_rejections": 0,
            "average_interaction_rounds": 2.0,
            "p50_model_latency_ms": 10,
            "p95_model_latency_ms": 20,
            "estimated_cost_usd": 0.001,
        },
        "cases": [
            {
                "index": 0,
                "reward": 1,
                "turns": 2,
                "failure_classification": "none",
                "tool_calls": [{"name": "execute_sql"}],
            }
        ],
        "limitations": ["five-sample subset", "isolated DB", "no Qwen"],
    }
    assert "不是 300 条标准集" in render_agentbench_markdown(report)
    assert "five-sample subset" in render_agentbench_markdown(report, language="en")


def test_dbbench_decision_guard_is_general_and_not_fixture_specific() -> None:
    assert "aggregate COUNT" in DBBENCH_DECISION_GUARD
    assert "returned column and value type" in DBBENCH_DECISION_GUARD
    assert "Clary" not in DBBENCH_DECISION_GUARD
    assert "Jarabacoa" not in DBBENCH_DECISION_GUARD


def test_semantic_preflight_rejects_non_count_query_for_count_question() -> None:
    wrong = ModelResponse(
        content="",
        tool_calls=(
            ToolCall(
                "call-1",
                "execute_sql",
                {"query": "SELECT * FROM contestants WHERE Contestant = 'A'"},
            ),
        ),
    )
    corrected = ModelResponse(
        content="",
        tool_calls=(
            ToolCall(
                "call-2",
                "execute_sql",
                {"query": "SELECT COUNT(Represents) FROM contestants"},
            ),
        ),
    )
    question = "Name the total number of represents for this contestant"
    assert "COUNT" in (_semantic_preflight(question, wrong) or "")
    assert _semantic_preflight(question, corrected) is None
