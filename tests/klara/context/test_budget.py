from __future__ import annotations

from klara.context.budget import compact_transcript, estimate_message_tokens
from klara.context.policy import ContextPolicy
from klara.core.messages import KlaraMessage


def policy(**overrides) -> ContextPolicy:
    values = {
        "max_input_tokens": 800,
        "reserved_system_tokens": 100,
        "reserved_output_tokens": 100,
        "recent_messages": 3,
        "minimum_recent_messages": 2,
        "summary_max_chars": 600,
        "tool_result_max_chars": 160,
        "chars_per_token": 4,
    }
    values.update(overrides)
    return ContextPolicy(**values)


def test_compaction_keeps_recent_messages_and_summarizes_older_context() -> None:
    messages = [
        KlaraMessage(role="user", content=f"old user {index} " + "u" * 420)
        if index % 2 == 0
        else KlaraMessage(role="assistant", content=f"old answer {index} " + "a" * 420)
        for index in range(8)
    ]
    messages.extend(
        [
            KlaraMessage(role="user", content="latest user request"),
            KlaraMessage(role="assistant", content="latest answer"),
        ]
    )

    prepared, summary, metrics = compact_transcript(messages, policy=policy())

    assert prepared[-2:] == messages[-2:]
    assert "old user" in summary
    assert metrics["messages_summarized"] > 0
    assert metrics["after_estimated_tokens"] <= metrics["budget_tokens"]
    assert metrics["summary_sha256"]


def test_old_tool_results_are_micro_compacted_with_provenance() -> None:
    messages = [
        KlaraMessage(role="assistant", content=""),
        KlaraMessage(role="tool", name="web_fetch", tool_call_id="fetch-1", content="source content " + "x" * 900),
        KlaraMessage(role="user", content="continue"),
        KlaraMessage(role="assistant", content="working"),
        KlaraMessage(role="user", content="finish"),
    ]

    prepared, _, metrics = compact_transcript(messages, policy=policy(max_input_tokens=2_000))

    tool = next(message for message in prepared if message.role == "tool")
    assert "older tool observation compacted" in tool.content
    assert "sha256=" in tool.content
    assert tool.tool_call_id == "fetch-1"
    assert metrics["tool_results_micro_compacted"] == 1


def test_individually_oversized_current_message_is_hard_bounded() -> None:
    messages = [KlaraMessage(role="user", content="START " + "x" * 9000 + " END")]

    prepared, _, metrics = compact_transcript(messages, policy=policy())

    assert estimate_message_tokens(prepared) <= metrics["budget_tokens"]
    assert "START" in prepared[0].content
    assert "END" in prepared[0].content
    assert "message clipped for context budget" in prepared[0].content
    assert metrics["messages_hard_trimmed"] == 1


def test_context_policy_rejects_impossible_budget() -> None:
    try:
        ContextPolicy(max_input_tokens=500, reserved_system_tokens=250, reserved_output_tokens=200)
    except ValueError as exc:
        assert "transcript budget" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("impossible context budget must fail")
