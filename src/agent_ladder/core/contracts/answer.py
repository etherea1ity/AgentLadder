from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator


class AnswerState(BaseModel):
    """Agent output state for one minimal-agent answer."""

    ask_id: str
    answer: str
    model: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("ask_id", "answer", "model")
    @classmethod
    def text_fields_must_not_be_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("field must not be empty")
        return text
