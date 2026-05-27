from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


TokenSource = Literal["reported", "estimated", "unknown"]


class TokenUsage(BaseModel):
    """Input/output token usage for one LLM call.

    Agent Ladder uses input/output wording for teaching clarity while adapters
    can still map provider-native prompt/completion names onto these fields.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    source: TokenSource = "unknown"

    @field_validator("input_tokens", "output_tokens", "total_tokens")
    @classmethod
    def optional_counts_must_not_be_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("token count must not be negative")
        return value

    @model_validator(mode="after")
    def fill_total_tokens(self) -> "TokenUsage":
        if self.total_tokens is None and self.input_tokens is not None and self.output_tokens is not None:
            self.total_tokens = self.input_tokens + self.output_tokens
        return self

    @classmethod
    def from_provider_counts(
        cls,
        *,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        source: TokenSource,
    ) -> "TokenUsage":
        return cls(input_tokens=prompt_tokens, output_tokens=completion_tokens, source=source)
