from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class AskState(BaseModel):
    """User input state for one minimal-agent question."""

    ask_id: str = Field(default_factory=lambda: f"ask_{uuid4().hex}")
    question: str
    language: str = "auto"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("question")
    @classmethod
    def question_must_not_be_empty(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("question must not be empty")
        return question
