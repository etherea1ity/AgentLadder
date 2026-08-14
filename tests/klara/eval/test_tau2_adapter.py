from __future__ import annotations

from dataclasses import dataclass

from klara.eval.tau2_adapter import (
    build_tau2_system_prompt,
    tau2_messages_to_klara,
    tau2_tools_to_klara,
)
from klara.eval.tau2_live import render_tau2_markdown


class FakeTool:
    name = "create_task"
    openai_schema = {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create one task.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
        },
    }


@dataclass
class FakeCall:
    id: str
    name: str
    arguments: dict


@dataclass
class FakeMessage:
    role: str
    content: str | None = None
    tool_calls: list[FakeCall] | None = None
    id: str = ""


def test_tau2_tool_schema_is_preserved() -> None:
    specs = tau2_tools_to_klara([FakeTool()])
    assert specs[0].name == "create_task"
    assert specs[0].input_schema["required"] == ["title"]


def test_tau2_transcript_preserves_tool_result_join() -> None:
    messages = tau2_messages_to_klara(
        [
            FakeMessage(role="user", content="Create it."),
            FakeMessage(
                role="assistant",
                tool_calls=[FakeCall("call-1", "create_task", {"title": "A"})],
            ),
            FakeMessage(role="tool", id="call-1", content='{"task_id":"task_1"}'),
        ]
    )
    assert messages[1].tool_calls[0].arguments == {"title": "A"}
    assert messages[2].tool_call_id == "call-1"
    assert messages[2].name == "create_task"


def test_tau2_prompt_keeps_persona_policy_and_protocol() -> None:
    prompt = build_tau2_system_prompt(persona="You are Klara.", domain_policy="Never delete.")
    assert "You are Klara." in prompt
    assert "Never delete." in prompt
    assert "never do both" in prompt


def test_tau2_report_states_adapter_boundary() -> None:
    report = {
        "passed": True,
        "adapter": {"candidate_model": "deepseek/deepseek-v4-flash"},
        "metrics": {"total_tasks": 1, "avg_reward": 1.0, "pass_hat_ks": {1: 1.0}},
        "cases": [
            {
                "task_id": "create_task_1",
                "reward": 1.0,
                "tool_names": ["create_task"],
                "termination_reason": "user_stop",
            }
        ],
        "limitations": ["official mock only", "same-model user", "not full runtime"],
    }
    zh = render_tau2_markdown(report)
    en = render_tau2_markdown(report, language="en")
    assert "不是完整 AgentLadder 产品运行时" in zh
    assert "not full runtime" in en
