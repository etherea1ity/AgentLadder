from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


RunStatus = Literal["queued", "thinking", "streaming", "completed", "failed", "cancelled"]
MessageStatus = Literal["idle", "running", "completed", "failed", "cancelled"]
TokenSource = Literal["reported", "estimated", "unknown"]
RunEventType = Literal[
    "run_created",
    "thinking_started",
    "llm_call_started",
    "answer_streaming_started",
    "answer_delta",
    "llm_call_completed",
    "tool_call_started",
    "tool_call_completed",
    "tool_call_failed",
    "policy_stop",
    "hook_placement_started",
    "hook_placement_completed",
    "thinking_summary_started",
    "thinking_summary_completed",
    "provider_reasoning_delta",
    "provider_reasoning_completed",
    "assistant_activity_delta",
    "assistant_activity_completed",
    "activity_fact_recorded",
    "web_research.started",
    "web_research.state_updated",
    "web_search.started",
    "web_search.completed",
    "web_fetch.started",
    "web_fetch.completed",
    "evidence.candidate_recorded",
    "evidence.source_recorded",
    "evidence.readiness_evaluated",
    "final_answer.blocked",
    "final_answer.allowed",
    "context.compacted",
    "run_completed",
    "run_failed",
    "run_cancelled",
    "module_started",
    "module_completed",
    "module_failed",
    "trace_saved",
]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class SessionRecord(BaseModel):
    session_id: str = Field(default_factory=lambda: new_id("sess"))
    title: str = "Untitled"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    deleted_at: str | None = None
    message_ids: list[str] = Field(default_factory=list)


class MessageRecord(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    session_id: str
    role: Literal["user", "assistant"]
    content: str = ""
    run_id: str | None = None
    status: MessageStatus = "idle"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str | None = None


class RunError(BaseModel):
    code: str | None = None
    message: str
    stage: str | None = None


class RunRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: new_id("run"))
    session_id: str
    user_message_id: str
    assistant_message_id: str
    status: RunStatus = "queued"
    model: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    token_source: TokenSource | None = None
    trace_saved: bool = False
    error: RunError | None = None
    thinking_enabled: bool | None = None


class RunEventRecord(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    run_id: str
    event_type: RunEventType
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class CreateSessionResponse(SessionRecord):
    pass


class ListSessionsResponse(BaseModel):
    sessions: list[SessionRecord]


class SessionDetailResponse(BaseModel):
    session: SessionRecord
    messages: list[MessageRecord]
    runs: list[RunRecord]
    events: list[RunEventRecord] = Field(default_factory=list)


class RenameSessionRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title must not be empty")
        return title[:80]


class DeleteSessionResponse(BaseModel):
    session_id: str
    deleted: bool
    deleted_at: str


class CreateRunRequest(BaseModel):
    session_id: str
    question: str
    model: str | None = None
    thinking_enabled: bool | None = None

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("question must not be empty")
        return question

    @field_validator("model")
    @classmethod
    def model_not_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        model = value.strip()
        if not model:
            return None
        return model[:120]


class CreateRunResponse(BaseModel):
    run_id: str
    session_id: str
    user_message_id: str
    assistant_message_id: str
    status: RunStatus
    events_url: str


class RunDetailResponse(BaseModel):
    run: RunRecord
    events: list[RunEventRecord]
    trace: dict[str, Any] | None = None


class RunEventsResponse(BaseModel):
    events: list[RunEventRecord]


class CancelRunResponse(BaseModel):
    run_id: str
    status: RunStatus


class ModelOption(BaseModel):
    id: str
    model: str
    label: str
    use_when: str | None = None
    supports_thinking: bool = False
    default_thinking: bool = False


class ListModelsResponse(BaseModel):
    default_model: str
    models: list[ModelOption]
