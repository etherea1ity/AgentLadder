from __future__ import annotations

from pathlib import Path


def test_persona_prompt_uses_readable_klara_chinese() -> None:
    """The persona prompt should not feed mojibake identity text to the model."""

    prompt = (Path("src") / "klara" / "prompts" / "persona.md").read_text(
        encoding="utf-8"
    )

    assert "克拉拉" in prompt
    assert "鍏嬫媺" not in prompt
    assert "嘿嘿，谢谢你。克拉拉会继续努力的。" in prompt
