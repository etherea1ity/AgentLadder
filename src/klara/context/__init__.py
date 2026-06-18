"""Context preparation layer for Klara runtime."""

from klara.context.history import prepare_conversation_history, sanitize_history_content
from klara.context.runtime import build_runtime_context_prompt, build_system_prompt
from klara.context.timestamps import (
    build_message_timestamp_prefix,
    stamp_user_message_content,
)

__all__ = [
    "build_message_timestamp_prefix",
    "build_runtime_context_prompt",
    "build_system_prompt",
    "prepare_conversation_history",
    "sanitize_history_content",
    "stamp_user_message_content",
]
