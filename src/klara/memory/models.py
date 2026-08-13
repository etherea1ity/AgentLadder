"""Typed long-term-memory contracts owned outside Klara core."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    """Return a sortable timezone-aware UTC timestamp."""

    return datetime.now(UTC).isoformat()


class MemoryKind(StrEnum):
    """Memory classes with different product meanings."""

    USER_PREFERENCE = "user_preference"
    STABLE_FACT = "stable_fact"
    EPISODIC = "episodic"
    TASK = "task"
    AGENT_LEARNING = "agent_learning"


class MemorySensitivity(StrEnum):
    """Content sensitivity used by future permission and retention policy."""

    STANDARD = "standard"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class MemoryStatus(StrEnum):
    """Lifecycle state for a durable memory record."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"


class CandidateStatus(StrEnum):
    """Review state for an automatic memory proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MemoryScope:
    """Every read and write is partitioned by tenant and user."""

    tenant_id: str
    user_id: str
    agent_id: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.user_id.strip():
            raise ValueError("memory_scope_requires_tenant_and_user")


@dataclass(frozen=True)
class MemoryProvenance:
    """Explain why a record exists without storing an entire conversation."""

    source_type: str
    actor_id: str
    source_id: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class MemoryRecord:
    """One typed, scoped, temporal long-term-memory fact."""

    memory_id: str
    scope: MemoryScope
    kind: MemoryKind
    content: str
    sensitivity: MemorySensitivity
    provenance: MemoryProvenance
    created_at: str
    updated_at: str
    confidence: float = 1.0
    valid_from: str | None = None
    valid_to: str | None = None
    expires_at: str | None = None
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_owner_dict(self) -> dict[str, Any]:
        """Return the complete owner-visible record."""

        value = asdict(self)
        value["kind"] = self.kind.value
        value["sensitivity"] = self.sensitivity.value
        value["status"] = self.status.value
        return value

    def to_trace_dict(self) -> dict[str, Any]:
        """Return lifecycle metadata without memory content or provenance notes."""

        return {
            "memory_id": self.memory_id,
            "kind": self.kind.value,
            "sensitivity": self.sensitivity.value,
            "status": self.status.value,
            "confidence": self.confidence,
            "has_expiry": self.expires_at is not None,
            "has_temporal_bounds": self.valid_from is not None or self.valid_to is not None,
            "content_exposed": False,
        }


@dataclass(frozen=True)
class MemoryCandidate:
    """Uncommitted automatic proposal that requires explicit review."""

    candidate_id: str
    scope: MemoryScope
    kind: MemoryKind
    content: str
    sensitivity: MemorySensitivity
    provenance: MemoryProvenance
    created_at: str
    confidence: float
    status: CandidateStatus = CandidateStatus.PENDING

    def to_owner_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        value["sensitivity"] = self.sensitivity.value
        value["status"] = self.status.value
        return value


@dataclass(frozen=True)
class MemoryAuditEvent:
    """Content-free immutable audit fact."""

    audit_id: str
    tenant_id: str
    user_id: str
    record_id: str
    operation: str
    actor_id: str
    occurred_at: str
    content_sha256: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_owner_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemorySearchHit:
    """One ranked result with inspectable score components."""

    record: MemoryRecord
    score: float
    lexical_score: float
    semantic_score: float
    entity_score: float
    recency_score: float
    temporal_score: float

    def to_owner_dict(self) -> dict[str, Any]:
        return {
            **self.record.to_owner_dict(),
            "score": round(self.score, 6),
            "score_components": {
                "lexical": round(self.lexical_score, 6),
                "semantic": round(self.semantic_score, 6),
                "entity": round(self.entity_score, 6),
                "recency": round(self.recency_score, 6),
                "temporal": round(self.temporal_score, 6),
            },
        }


def new_memory_id() -> str:
    return f"mem_{uuid4().hex}"


def new_candidate_id() -> str:
    return f"mcand_{uuid4().hex}"


def new_audit_id() -> str:
    return f"maudit_{uuid4().hex}"
