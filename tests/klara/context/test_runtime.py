from __future__ import annotations

from datetime import UTC, datetime

from klara.context.runtime import build_runtime_context_prompt, build_system_prompt


def test_runtime_context_includes_date_without_minute_precision() -> None:
    prompt = build_runtime_context_prompt(
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 18, 12, 34, tzinfo=UTC),
    )

    assert "Conversation date: Thursday, June 18, 2026" in prompt
    assert "User timezone: Asia/Shanghai" in prompt
    assert "UTC date: 2026-06-18" in prompt
    assert "do not call current_time only to learn today's date" in prompt
    assert "call web_search before answering from memory" in prompt
    assert "Search snippets are candidates, not evidence" in prompt
    assert "If fetched pages disagree" in prompt
    assert "relevant to the user's request" in prompt
    assert "preferred_source" not in prompt
    assert "candidate_source" not in prompt
    assert "do not invent quotes, numeric ratings" in prompt
    assert "source-limited analysis" not in prompt
    assert "Fixtures are not results" not in prompt
    assert "Call current_time only for exact wall-clock time" in prompt
    assert "Call web_fetch for source text from a specific public URL" in prompt
    assert "12:34" not in prompt
    assert "20:34" not in prompt


def test_system_prompt_appends_runtime_context_to_persona() -> None:
    prompt = build_system_prompt(
        persona="You are Klara.",
        timezone_name="UTC",
        now=datetime(2026, 6, 18, 0, 1, tzinfo=UTC),
    )

    assert prompt.startswith("You are Klara.")
    assert "<runtime_context>" in prompt
    assert "Conversation date: Thursday, June 18, 2026" in prompt
