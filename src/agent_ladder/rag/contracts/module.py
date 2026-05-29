"""Public module-result contracts for observable Klara runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ModuleStatus = Literal["pending", "running", "completed", "failed", "skipped"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class ModuleResult(BaseModel):
    """One observable action card in the right-side Run Chain."""

    module_id: str
    module_name: str
    status: ModuleStatus = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: int | None = None
    input_summary: str = ""
    output_summary: str = ""
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @field_validator("module_id", "module_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("field must not be empty")
        return text

    def started(self) -> "ModuleResult":
        return self.model_copy(update={"status": "running", "started_at": utc_now()})

    def completed(self, *, output_summary: str | None = None, output_payload: dict[str, Any] | None = None) -> "ModuleResult":
        finished = utc_now()
        latency_ms = None
        if self.started_at is not None:
            latency_ms = max(0, int((finished - self.started_at).total_seconds() * 1000))
        return self.model_copy(
            update={
                "status": "completed",
                "completed_at": finished,
                "latency_ms": latency_ms,
                "output_summary": output_summary if output_summary is not None else self.output_summary,
                "output_payload": output_payload if output_payload is not None else self.output_payload,
            }
        )

    def failed(self, error: str) -> "ModuleResult":
        finished = utc_now()
        latency_ms = None
        if self.started_at is not None:
            latency_ms = max(0, int((finished - self.started_at).total_seconds() * 1000))
        return self.model_copy(update={"status": "failed", "completed_at": finished, "latency_ms": latency_ms, "error": error})
