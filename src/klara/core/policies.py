from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StopReason(StrEnum):
    FINAL = "final"
    MAX_TURNS = "max_turns"
    FAILED = "failed"


@dataclass(frozen=True)
class LoopPolicy:
    max_turns: int = 4

    def __post_init__(self) -> None:
        if self.max_turns < 1:
            raise ValueError("max_turns must be at least 1")
