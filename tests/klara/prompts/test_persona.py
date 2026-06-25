from __future__ import annotations

import re
from pathlib import Path


def test_persona_prompt_is_short_ascii_and_lightweight() -> None:
    """The runtime persona should stay concise and avoid heavy rule blocks."""

    prompt = (Path("src") / "klara" / "prompts" / "persona.md").read_text(
        encoding="utf-8"
    )

    assert len(prompt.splitlines()) <= 12
    assert not re.search(r"[\u4e00-\u9fff]", prompt)
    assert "Klara is clear, warm, curious, and practical." in prompt
    assert "Match the user's language." in prompt
    assert "Be honest about uncertainty" in prompt
    assert "call `update_activity` before the other tool calls" in prompt
    assert "Use it to write Klara's public thinking" in prompt
    assert "update_activity.text" not in prompt
    assert "not the final answer" in prompt
    assert "Keep private reasoning out of user-facing text." in prompt
    assert "Do not " not in prompt
    assert "Good praise response style" not in prompt


def test_persona_prompt_keeps_only_generic_tool_guidance() -> None:
    """Persona should not duplicate detailed runtime web policy."""

    prompt = (Path("src") / "klara" / "prompts" / "persona.md").read_text(
        encoding="utf-8"
    )

    assert "use available runtime tools when they matter" in prompt
    assert "image generation" not in prompt
    assert "web_search for changing external facts" not in prompt
    assert "source-limited analysis" not in prompt
