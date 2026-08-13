"""Typed context budgets shared by product entrypoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextPolicy:
    """Deterministic transcript and summary budgets for one model request."""

    max_input_tokens: int = 16_000
    reserved_system_tokens: int = 2_500
    reserved_output_tokens: int = 3_500
    recent_messages: int = 10
    minimum_recent_messages: int = 4
    summary_max_chars: int = 2_400
    tool_result_max_chars: int = 1_200
    chars_per_token: int = 4

    def __post_init__(self) -> None:
        if self.max_input_tokens < 256:
            raise ValueError("max_input_tokens must be at least 256")
        if self.reserved_system_tokens < 0 or self.reserved_output_tokens < 0:
            raise ValueError("context reserves must be non-negative")
        if self.transcript_budget_tokens < 128:
            raise ValueError("context transcript budget must be at least 128 tokens")
        if self.recent_messages < 1:
            raise ValueError("recent_messages must be positive")
        if not 1 <= self.minimum_recent_messages <= self.recent_messages:
            raise ValueError("minimum_recent_messages must be within recent_messages")
        if self.summary_max_chars < 128 or self.tool_result_max_chars < 64:
            raise ValueError("context text budgets are too small")
        if self.chars_per_token < 1:
            raise ValueError("chars_per_token must be positive")

    @property
    def transcript_budget_tokens(self) -> int:
        """Return tokens available after frozen system/output reserves."""

        return (
            self.max_input_tokens
            - self.reserved_system_tokens
            - self.reserved_output_tokens
        )

    def to_public_dict(self) -> dict[str, int]:
        """Return safe budget metadata for run profiles and traces."""

        return {
            "max_input_tokens": self.max_input_tokens,
            "reserved_system_tokens": self.reserved_system_tokens,
            "reserved_output_tokens": self.reserved_output_tokens,
            "transcript_budget_tokens": self.transcript_budget_tokens,
            "recent_messages": self.recent_messages,
            "minimum_recent_messages": self.minimum_recent_messages,
            "summary_max_chars": self.summary_max_chars,
            "tool_result_max_chars": self.tool_result_max_chars,
            "chars_per_token": self.chars_per_token,
        }
