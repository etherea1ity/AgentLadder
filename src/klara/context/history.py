"""Conversation-history preparation for model-visible context."""

from __future__ import annotations

import re
from collections.abc import Iterable

from klara.core.messages import KlaraMessage

LOCAL_ASSET_URL_PATTERN = (
    r"(?:https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?)?"
    r"/api/assets/local\?path=data/assets/images/[^\s)]+?\."
    r"(?:png|jpg|jpeg|webp|gif|svg)"
)
MARKDOWN_LOCAL_ASSET = re.compile(
    rf"!?\[[^\]\n]*\]\(({LOCAL_ASSET_URL_PATTERN})\)",
    re.IGNORECASE,
)
BARE_LOCAL_ASSET = re.compile(LOCAL_ASSET_URL_PATTERN, re.IGNORECASE)
GENERATED_IMAGE_PLACEHOLDER = "[generated image omitted from prior context]"


def prepare_conversation_history(
    messages: Iterable[KlaraMessage],
    *,
    max_messages: int,
) -> tuple[KlaraMessage, ...]:
    """Sanitize and bound prior conversation turns before a new run.

    Args:
        messages: Completed user/assistant turns from the app store.
        max_messages: Maximum messages to expose to the next model call.

    Returns:
        A tuple of sanitized messages, preserving role order and recent turns.
    """

    prepared: list[KlaraMessage] = []
    # Preserve prior turn order while removing local media URLs from history.
    for message in messages:
        prepared.append(
            KlaraMessage(
                role=message.role,
                content=sanitize_history_content(message.content),
                name=message.name,
                tool_call_id=message.tool_call_id,
                tool_calls=message.tool_calls,
            )
        )
    return tuple(prepared[-max_messages:])


def sanitize_history_content(content: str) -> str:
    """Replace local generated-asset links with a compact context placeholder.

    Args:
        content: Message content stored by the app.

    Returns:
        Content safe to replay in model history without leaking stale asset URLs.
    """

    without_markdown = MARKDOWN_LOCAL_ASSET.sub(GENERATED_IMAGE_PLACEHOLDER, content)
    return BARE_LOCAL_ASSET.sub(GENERATED_IMAGE_PLACEHOLDER, without_markdown)
