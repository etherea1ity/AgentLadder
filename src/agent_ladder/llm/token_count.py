from __future__ import annotations

from math import ceil

from agent_ladder.llm.base import Message


def estimate_text_tokens(text: str) -> int:
    """Model-agnostic token estimate for local teaching telemetry.

    Exact tokenizers differ by provider/model. v0.1 uses this deterministic
    fallback only when the provider does not report usage, so every run can show
    token-like cost signals without coupling the core to one tokenizer package.
    """
    tokens = 0
    ascii_run = 0

    def flush_ascii() -> None:
        nonlocal ascii_run, tokens
        if ascii_run:
            tokens += max(1, ceil(ascii_run / 4))
            ascii_run = 0

    for char in text:
        codepoint = ord(char)
        if char.isspace():
            flush_ascii()
        elif _is_cjk_or_emoji(codepoint):
            flush_ascii()
            tokens += 1
        elif char.isalnum() or char in {"_", "-"}:
            ascii_run += 1
        else:
            flush_ascii()
            tokens += 1

    flush_ascii()
    return tokens


def estimate_messages_tokens(messages: list[Message]) -> int:
    """Estimate chat prompt tokens with a small per-message framing cost."""
    return sum(estimate_text_tokens(message.get("content", "")) + 4 for message in messages)


def _is_cjk_or_emoji(codepoint: int) -> bool:
    return (
        0x3400 <= codepoint <= 0x9FFF  # CJK
        or 0x3040 <= codepoint <= 0x30FF  # Japanese kana
        or 0xAC00 <= codepoint <= 0xD7AF  # Hangul
        or 0x1F300 <= codepoint <= 0x1FAFF  # emoji/symbol pictographs
    )
