from __future__ import annotations

from klara.context.history import (
    GENERATED_IMAGE_PLACEHOLDER,
    prepare_conversation_history,
    sanitize_history_content,
)
from klara.core.messages import KlaraMessage


def test_sanitize_history_content_replaces_local_image_markdown() -> None:
    """Prior generated image URLs should not be replayed as fresh context."""

    content = (
        "![Generated image](/api/assets/local?path=data/assets/images/20260617/a.png)\n"
        "This is Klara's generated image."
    )

    sanitized = sanitize_history_content(content)

    assert "/api/assets/local" not in sanitized
    assert GENERATED_IMAGE_PLACEHOLDER in sanitized
    assert "This is Klara's generated image." in sanitized


def test_prepare_conversation_history_sanitizes_and_bounds_messages() -> None:
    """History preparation should preserve recent turns but scrub local media URLs."""

    messages = [
        KlaraMessage(role="user", content="draw"),
        KlaraMessage(
            role="assistant",
            content="[Open generated image](/api/assets/local?path=data/assets/images/x.webp)",
        ),
        KlaraMessage(role="user", content="search recent public news"),
    ]

    history = prepare_conversation_history(messages, max_messages=2)

    assert [message.role for message in history] == ["assistant", "user"]
    assert history[0].content == GENERATED_IMAGE_PLACEHOLDER
    assert history[1].content == "search recent public news"


def test_prepare_history_keeps_all_sanitized_messages_without_legacy_bound() -> None:
    messages = tuple(
        KlaraMessage(role="user", content=f"message {index}") for index in range(20)
    )

    history = prepare_conversation_history(messages)

    assert len(history) == 20
