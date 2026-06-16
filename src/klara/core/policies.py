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

    The minimal runtime only needs max-turn control. Richer policy should live
    outside core or enter through deliberate extensions to this contract.
    """

    # Max turns prevents a model from requesting tools forever.
    max_turns: int = 12

    def __post_init__(self) -> None:
        """Validate policy values as soon as the immutable policy is created."""

        if self.max_turns < 1:
            raise ValueError("max_turns must be at least 1")
