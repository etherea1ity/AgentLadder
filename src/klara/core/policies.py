"""Loop policy primitives for Klara core."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StopReason(StrEnum):
    """Explicit reasons a Klara loop can stop."""

    FINAL = "final"
    MAX_TURNS = "max_turns"
    MAX_TOOL_CALLS = "max_tool_calls"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    NO_PROGRESS = "no_progress"
    FAILED = "failed"


@dataclass(frozen=True)
class LoopPolicy:
    """Bounded execution policy for the runtime loop.

    Max turns is the final fuse. Tool budgets are the normal protection against
    loops that keep requesting tools without making user-visible progress.
    """

    # Max turns prevents a model from reasoning forever across non-tool turns.
    max_turns: int = 24
    # Max total tool calls prevents broad requests from becoming unbounded.
    max_tool_calls: int = 48
    # Max identical name+arguments calls catches repeated retries of one action.
    max_repeated_tool_calls: int = 3
    # Max identical final-answer blocks before forcing a no-tool finalization.
    max_repeated_final_blocks: int = 2
    # Prompt-too-long may compact and retry the same model request this many times.
    max_prompt_recovery_attempts: int = 1

    def __post_init__(self) -> None:
        """Validate policy values as soon as the immutable policy is created."""

        if self.max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least 1")
        if self.max_repeated_tool_calls < 1:
            raise ValueError("max_repeated_tool_calls must be at least 1")
        if self.max_repeated_final_blocks < 1:
            raise ValueError("max_repeated_final_blocks must be at least 1")
        if self.max_prompt_recovery_attempts < 0:
            raise ValueError("max_prompt_recovery_attempts must be non-negative")
