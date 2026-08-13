from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from klara.planning.todo import TodoPlan


RunStatus = Literal["queued", "thinking", "streaming", "completed", "failed", "cancelled"]
MessageStatus = Literal["idle", "running", "completed", "failed", "cancelled"]
TokenSource = Literal["reported", "estimated", "unknown"]
RunEventType = Literal[
    "run_created",
    "run_profile_frozen",
    "todo_plan_updated",
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
    "web_research.no_viable_action",
    "web_search.started",
    "web_search.completed",
    "web_search.failed",
    "web_fetch.started",
    "web_fetch.completed",
    "web_fetch.failed",
    "evidence.candidate_recorded",
    "evidence.source_recorded",
    "evidence.readiness_evaluated",
    "evidence.answer_submitted",
    "evidence.submission_rejected",
    "evidence.verification_completed",
    "evidence.verification_failed",
    "final_answer.blocked",
    "final_answer.allowed",
    "final_answer.no_progress_stopped",
    "context.compacted",
    "context.assembled",
    "context.budget_evaluated",
    "context.prompt_recovery_applied",
    "provider.attempt_started",
    "provider.attempt_completed",
    "provider.attempt_failed",
    "provider.retry_scheduled",
    "model_route.candidate_started",
    "model_route.candidate_failed",
    "model_route.fallback_started",
    "model_route.candidate_completed",
    "model_call.failed",
    "prompt_recovery.started",
    "prompt_recovery.completed",
    "skills.catalog_ready",
    "skills.selected",
    "skills.loaded",
    "skills.load_rejected",
    "memory.review_completed",
    "memory.remembered",
    "memory.retrieved",
    "memory.updated",
    "memory.forgotten",
    "memory.deleted",
    "permission.requested",
    "permission.allowed",
    "permission.denied",
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
    client_created_at: str | None = None
    client_timezone: str | None = None
    client_utc_offset_minutes: int | None = None


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
    todo_plan: TodoPlan | None = None


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


class ClientContext(BaseModel):
    timestamp: str | None = None
    timezone: str | None = None
    utc_offset_minutes: int | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_not_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        timestamp = value.strip()
        if not timestamp:
            return None
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None
        return timestamp[:80]

    @field_validator("timezone")
    @classmethod
    def timezone_not_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        timezone = value.strip()
        if not timezone:
            return None
        return timezone[:80]

    @field_validator("utc_offset_minutes")
    @classmethod
    def utc_offset_in_reasonable_range(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return max(-14 * 60, min(14 * 60, value))


class CreateRunRequest(BaseModel):
    session_id: str
    question: str
    model: str | None = None
    thinking_enabled: bool | None = None
    client_context: ClientContext | None = None

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
    capabilities: list[str] = Field(default_factory=list)
    supports_thinking: bool = False
    default_thinking: bool = False


class ListModelsResponse(BaseModel):
    default_model: str
    models: list[ModelOption]


class SkillOption(BaseModel):
    """Safe metadata for one resolved procedural Skill."""

    name: str
    description: str
    version: str
    scope: Literal["built_in", "user", "project"]
    source: str
    sha256: str
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    shadowed_scopes: list[str] = Field(default_factory=list)


class ListSkillsResponse(BaseModel):
    """Read-only resolved Skill catalog response."""

    schema_version: Literal["klara.skills-catalog.v1"]
    precedence: list[str]
    body_loading: Literal["on_demand"]
    skills: list[SkillOption]


MemoryKindValue = Literal[
    "user_preference", "stable_fact", "episodic", "task", "agent_learning"
]
MemorySensitivityValue = Literal["standard", "personal", "sensitive", "restricted"]


class MemoryRecordResponse(BaseModel):
    memory_id: str
    scope: dict[str, Any]
    kind: MemoryKindValue
    content: str
    sensitivity: MemorySensitivityValue
    provenance: dict[str, Any]
    created_at: str
    updated_at: str
    confidence: float
    valid_from: str | None = None
    valid_to: str | None = None
    expires_at: str | None = None
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    status: Literal["active", "superseded", "forgotten"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ListMemoriesResponse(BaseModel):
    schema_version: Literal["klara.memory-list.v1"]
    records: list[MemoryRecordResponse]
    counts_by_kind: dict[str, int]


class CreateMemoryRequest(BaseModel):
    content: str
    kind: MemoryKindValue
    sensitivity: MemorySensitivityValue = "standard"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    ttl_seconds: int | None = Field(default=None, ge=1)

    @field_validator("content")
    @classmethod
    def memory_content_not_empty(cls, value: str) -> str:
        content = " ".join(value.split())
        if not content:
            raise ValueError("memory content must not be empty")
        return content


class UpdateMemoryRequest(BaseModel):
    content: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SearchMemoriesResponse(BaseModel):
    schema_version: Literal["klara.memory-search.v1"]
    query: str
    mode: str
    results: list[dict[str, Any]]


class DeleteMemoryResponse(BaseModel):
    memory_id: str
    deleted: bool
    content_sha256: str
    raw_content_occurrences: int
    deletion_verified: bool


PermissionEffectValue = Literal[
    "deny", "allow_once", "allow_task", "allow_standing"
]


class PermissionDecisionRequest(BaseModel):
    effect: PermissionEffectValue
    expires_seconds: int = Field(default=900, ge=1, le=30 * 24 * 60 * 60)
    parent_grant_id: str | None = None


class PermissionStateResponse(BaseModel):
    schema_version: Literal["klara.permissions-state.v1"]
    requests: list[dict[str, Any]]
    grants: list[dict[str, Any]]
    audit: list[dict[str, Any]]


class PermissionGrantResponse(BaseModel):
    grant_id: str
    request_id: str | None
    effect: PermissionEffectValue
    status: Literal["active", "consumed", "revoked", "expired"]
    scope: dict[str, Any]
    action: dict[str, Any]
    created_at: str
    expires_at: str
    remaining_uses: int | None = None
    parent_grant_id: str | None = None
    revoked_at: str | None = None
