from __future__ import annotations

from pathlib import Path


def test_persona_prompt_uses_readable_klara_chinese() -> None:
    """The persona prompt should not feed mojibake identity text to the model."""

    prompt = (Path("src") / "klara" / "prompts" / "persona.md").read_text(
        encoding="utf-8"
    )

    assert "克拉拉" in prompt
    assert "嘿嘿，谢谢你。克拉拉会继续努力的。" in prompt
    assert "鍏嬫媺鎷" not in prompt
    assert "閸忓濯" not in prompt


def test_persona_prompt_requires_source_urls_for_web_answers() -> None:
    """Web-backed answers should expose the URLs that supported them."""

    prompt = (Path("src") / "klara" / "prompts" / "persona.md").read_text(
        encoding="utf-8"
    )

    assert "After web_search for web-backed factual answers" in prompt
    assert "web_fetch to read at least one specific public URL" in prompt
    assert "mention the exact source URLs used" in prompt
    assert "prefer fetched preferred_source pages over candidate_source pages" in prompt
    assert "keep the answer narrow" in prompt
