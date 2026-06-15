"""Loop policy primitives for Klara core."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StopReason(StrEnum):
    """Explicit reasons a Klara loop can stop."""

    FINAL = "final"
    MAX_TURNS = "max_turns"
    FAILED = "failed"


@dataclass(frozen=True)
class LoopPolicy:
    """Bounded execution policy for the minimal loop.

    Chapter 1 only needs max-turn control. Later chapters can add richer policy
    outside core or through deliberate extensions to this contract.
    """

    # Max turns prevents a model from requesting tools forever.
    max_turns: int = 4

    def __post_init__(self) -> None:
        """Validate policy values as soon as the immutable policy is created."""

        if self.max_turns < 1:
            raise ValueError("max_turns must be at least 1")
