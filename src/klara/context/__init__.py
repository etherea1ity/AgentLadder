"""Context preparation layer for Klara runtime."""

from klara.context.assembly import ContextAssembly, WorkspaceProfile
from klara.context.budget import compact_transcript, estimate_message_tokens
from klara.context.controller import ContextController
from klara.context.history import prepare_conversation_history, sanitize_history_content
from klara.context.policy import ContextPolicy
from klara.context.response_contract import ResponseContractController
from klara.context.runtime import build_runtime_context_prompt, build_system_prompt
from klara.context.timestamps import (
    build_message_timestamp_prefix,
    stamp_user_message_content,
)

__all__ = [
    "build_message_timestamp_prefix",
    "build_runtime_context_prompt",
    "build_system_prompt",
    "compact_transcript",
    "ContextAssembly",
    "ContextController",
    "ContextPolicy",
    "ResponseContractController",
    "estimate_message_tokens",
    "prepare_conversation_history",
    "sanitize_history_content",
    "WorkspaceProfile",
    "stamp_user_message_content",
]
