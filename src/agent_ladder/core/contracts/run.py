from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from agent_ladder.core.contracts.usage import TokenSource, TokenUsage


class RunLog(BaseModel):
    """Observability state for one minimal-agent run."""

    run_id: str = Field(default_factory=lambda: f"run_{uuid4().hex}")
    ask_id: str
    model: str
    latency_ms: int | None = None
    # Provider-compatible names. In Agent Ladder docs/UI these mean input/output tokens.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    token_source: TokenSource = "unknown"
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("ask_id", "model")
    @classmethod
    def required_text_fields_must_not_be_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("field must not be empty")
        return text

    @field_validator("latency_ms", "prompt_tokens", "completion_tokens", "total_tokens")
    @classmethod
    def optional_counts_must_not_be_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("value must not be negative")
        return value

    @model_validator(mode="after")
    def fill_total_tokens(self) -> "RunLog":
        if self.total_tokens is None and self.prompt_tokens is not None and self.completion_tokens is not None:
            self.total_tokens = self.prompt_tokens + self.completion_tokens
        return self

    @property
    def usage(self) -> TokenUsage:
        return TokenUsage.from_provider_counts(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            source=self.token_source,
        )
