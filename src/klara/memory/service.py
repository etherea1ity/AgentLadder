"""Governed memory operations with tenant isolation and deletion proof."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any

from klara.memory.models import (
    CandidateStatus,
    MemoryAuditEvent,
    MemoryCandidate,
    MemoryKind,
    MemoryProvenance,
    MemoryRecord,
    MemoryScope,
    MemorySearchHit,
    MemorySensitivity,
    MemoryStatus,
    new_audit_id,
    new_candidate_id,
    new_memory_id,
    utc_now_iso,
)
from klara.memory.repository import SQLiteMemoryRepository
from klara.memory.retrieval import rank_memories
from klara.memory.semantic import EmbeddingProvider


class MemoryNotFoundError(LookupError):
    """Raised without revealing whether another tenant owns the id."""


class MemoryValidationError(ValueError):
    """Raised for invalid memory operations."""


class MemoryService:
    """Apply memory lifecycle policy above the durable repository."""

    def __init__(
        self,
        repository: SQLiteMemoryRepository,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    def remember(
        self,
        *,
        scope: MemoryScope,
        content: str,
        kind: MemoryKind,
        sensitivity: MemorySensitivity = MemorySensitivity.STANDARD,
        provenance: MemoryProvenance,
        confidence: float = 1.0,
        valid_from: str | None = None,
        valid_to: str | None = None,
        ttl_seconds: int | None = None,
        supersedes_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        """Persist an explicit or reviewed memory, optionally superseding an old fact."""

        normalized = _validate_content(content)
        _validate_confidence(confidence)
        now = utc_now_iso()
        previous = None
        if supersedes_id:
            previous = self._owned_record(scope, supersedes_id)
            if previous.status is not MemoryStatus.ACTIVE:
                raise MemoryValidationError("memory_supersedes_inactive_record")
        expires_at = None
        if ttl_seconds is not None:
            if ttl_seconds < 1:
                raise MemoryValidationError("memory_ttl_must_be_positive")
            expires_at = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()
        record = MemoryRecord(
            memory_id=new_memory_id(),
            scope=scope,
            kind=kind,
            content=normalized,
            sensitivity=sensitivity,
            provenance=provenance,
            created_at=now,
            updated_at=now,
            confidence=confidence,
            valid_from=valid_from or now,
            valid_to=valid_to,
            expires_at=expires_at,
            supersedes_id=supersedes_id,
            metadata=dict(metadata or {}),
        )
        if previous is not None:
            previous = replace(
                previous,
                status=MemoryStatus.SUPERSEDED,
                superseded_by_id=record.memory_id,
                valid_to=valid_from or now,
                updated_at=now,
            )
            self.repository.save_record(previous)
            self._audit(previous, "superseded", provenance.actor_id)
        self.repository.save_record(record)
        self._audit(record, "remembered", provenance.actor_id)
        return record

    def propose_candidate(
        self,
        *,
        scope: MemoryScope,
        content: str,
        kind: MemoryKind,
        sensitivity: MemorySensitivity,
        provenance: MemoryProvenance,
        confidence: float,
    ) -> MemoryCandidate:
        """Store an automatic proposal without making it retrievable memory."""

        normalized = _validate_content(content)
        _validate_confidence(confidence)
        candidate = MemoryCandidate(
            candidate_id=new_candidate_id(),
            scope=scope,
            kind=kind,
            content=normalized,
            sensitivity=sensitivity,
            provenance=provenance,
            created_at=utc_now_iso(),
            confidence=confidence,
        )
        self.repository.save_candidate(candidate)
        self._audit_candidate(candidate, "candidate_proposed", provenance.actor_id)
        return candidate

    def review_candidate(
        self,
        *,
        scope: MemoryScope,
        candidate_id: str,
        approve: bool,
        actor_id: str,
    ) -> MemoryRecord | None:
        """Approve a proposal into memory or reject and purge its raw content."""

        candidate = self.repository.get_candidate(scope, candidate_id)
        if candidate is None or candidate.status is not CandidateStatus.PENDING:
            raise MemoryNotFoundError("memory_candidate_not_found")
        operation = "candidate_approved" if approve else "candidate_rejected"
        self._audit_candidate(candidate, operation, actor_id)
        self.repository.hard_delete_candidate(scope, candidate_id)
        if not approve:
            return None
        return self.remember(
            scope=scope,
            content=candidate.content,
            kind=candidate.kind,
            sensitivity=candidate.sensitivity,
            provenance=MemoryProvenance(
                source_type="reviewed_candidate",
                actor_id=actor_id,
                source_id=candidate.candidate_id,
            ),
            confidence=candidate.confidence,
        )

    def update(
        self,
        *,
        scope: MemoryScope,
        memory_id: str,
        content: str,
        actor_id: str,
        confidence: float | None = None,
    ) -> MemoryRecord:
        """Create a new current record and retain the prior one as history."""

        previous = self._owned_record(scope, memory_id)
        return self.remember(
            scope=scope,
            content=content,
            kind=previous.kind,
            sensitivity=previous.sensitivity,
            provenance=MemoryProvenance(
                source_type="explicit_update",
                actor_id=actor_id,
                source_id=memory_id,
            ),
            confidence=previous.confidence if confidence is None else confidence,
            supersedes_id=memory_id,
            metadata=previous.metadata,
        )

    def forget(self, *, scope: MemoryScope, memory_id: str, actor_id: str) -> MemoryRecord:
        """Remove a record from retrieval while retaining owner-auditable history."""

        record = self._owned_record(scope, memory_id)
        forgotten = replace(record, status=MemoryStatus.FORGOTTEN, updated_at=utc_now_iso())
        self.repository.save_record(forgotten)
        self._audit(forgotten, "forgotten", actor_id)
        return forgotten

    def delete(self, *, scope: MemoryScope, memory_id: str, actor_id: str) -> dict[str, Any]:
        """Hard-delete raw content and return a verifiable deletion receipt."""

        record = self._owned_record(scope, memory_id)
        content_hash = _content_hash(record.content)
        deleted = self.repository.hard_delete_record(scope, memory_id)
        if not deleted:
            raise MemoryNotFoundError("memory_not_found")
        self._audit_hash(
            scope=scope,
            record_id=memory_id,
            operation="deleted",
            actor_id=actor_id,
            content_sha256=content_hash,
            details={"hard_delete": True},
        )
        remaining = self.repository.raw_content_occurrences(record.content)
        return {
            "memory_id": memory_id,
            "deleted": True,
            "content_sha256": content_hash,
            "raw_content_occurrences": remaining,
            "deletion_verified": remaining == 0,
        }

    def search(
        self,
        *,
        scope: MemoryScope,
        query: str,
        mode: str = "hybrid",
        at_time: str | None = None,
        limit: int = 8,
        kinds: set[MemoryKind] | None = None,
    ) -> list[MemorySearchHit]:
        """Search only records owned by the supplied tenant/user partition."""

        now = datetime.now(UTC)
        records = []
        # Repository already filters by tenant and user; lifecycle filters are second.
        for record in self.repository.list_records(scope):
            if kinds and record.kind not in kinds:
                continue
            if record.expires_at and _parse_time(record.expires_at) <= now:
                continue
            if at_time is None and record.status is not MemoryStatus.ACTIVE:
                continue
            if at_time is not None and record.status is MemoryStatus.FORGOTTEN:
                continue
            if scope.agent_id and record.scope.agent_id not in (None, scope.agent_id):
                continue
            records.append(record)
        return rank_memories(
            records,
            query=query,
            mode=mode,
            at_time=at_time,
            limit=limit,
            embedding_provider=self.embedding_provider,
        )

    def list_records(self, *, scope: MemoryScope, include_inactive: bool = False) -> list[MemoryRecord]:
        records = self.repository.list_records(scope)
        if include_inactive:
            return records
        return [record for record in records if record.status is MemoryStatus.ACTIVE]

    def export(self, *, scope: MemoryScope) -> dict[str, Any]:
        """Return an owner-visible portable export with lifecycle and audit records."""

        return {
            "schema_version": "klara.memory-export.v1",
            "scope": {"tenant_id": scope.tenant_id, "user_id": scope.user_id},
            "records": [record.to_owner_dict() for record in self.repository.list_records(scope)],
            "candidates": [item.to_owner_dict() for item in self.repository.list_candidates(scope)],
            "audit": [event.to_owner_dict() for event in self.repository.list_audit(scope)],
        }

    def audit(self, *, scope: MemoryScope) -> list[MemoryAuditEvent]:
        return self.repository.list_audit(scope)

    def consolidate(self, *, scope: MemoryScope, actor_id: str) -> dict[str, int]:
        """Supersede only exact normalized duplicates; never merge differing facts."""

        active = self.list_records(scope=scope)
        groups: dict[tuple[MemoryKind, str], list[MemoryRecord]] = {}
        for record in active:
            key = (record.kind, " ".join(record.content.casefold().split()))
            groups.setdefault(key, []).append(record)
        superseded = 0
        # Exact duplicates are reversible because their complete records remain stored.
        for records in groups.values():
            if len(records) < 2:
                continue
            records.sort(key=lambda item: (-item.confidence, item.created_at, item.memory_id))
            winner = records[0]
            for duplicate in records[1:]:
                updated = replace(
                    duplicate,
                    status=MemoryStatus.SUPERSEDED,
                    superseded_by_id=winner.memory_id,
                    valid_to=utc_now_iso(),
                    updated_at=utc_now_iso(),
                )
                self.repository.save_record(updated)
                self._audit(updated, "duplicate_consolidated", actor_id)
                superseded += 1
        return {"groups_reviewed": len(groups), "duplicates_superseded": superseded}

    def _owned_record(self, scope: MemoryScope, memory_id: str) -> MemoryRecord:
        record = self.repository.get_record(scope, memory_id)
        if record is None:
            raise MemoryNotFoundError("memory_not_found")
        return record

    def _audit(self, record: MemoryRecord, operation: str, actor_id: str) -> None:
        self._audit_hash(
            scope=record.scope,
            record_id=record.memory_id,
            operation=operation,
            actor_id=actor_id,
            content_sha256=_content_hash(record.content),
            details={"kind": record.kind.value, "status": record.status.value},
        )

    def _audit_candidate(self, candidate: MemoryCandidate, operation: str, actor_id: str) -> None:
        self._audit_hash(
            scope=candidate.scope,
            record_id=candidate.candidate_id,
            operation=operation,
            actor_id=actor_id,
            content_sha256=_content_hash(candidate.content),
            details={"kind": candidate.kind.value, "candidate": True},
        )

    def _audit_hash(
        self,
        *,
        scope: MemoryScope,
        record_id: str,
        operation: str,
        actor_id: str,
        content_sha256: str,
        details: dict[str, Any],
    ) -> None:
        self.repository.append_audit(
            MemoryAuditEvent(
                audit_id=new_audit_id(),
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                record_id=record_id,
                operation=operation,
                actor_id=actor_id,
                occurred_at=utc_now_iso(),
                content_sha256=content_sha256,
                details=details,
            )
        )


def _validate_content(content: str) -> str:
    normalized = " ".join(content.split())
    if not normalized:
        raise MemoryValidationError("memory_content_required")
    if len(normalized) > 8_000:
        raise MemoryValidationError("memory_content_too_large")
    return normalized


def _validate_confidence(confidence: float) -> None:
    if not 0.0 <= confidence <= 1.0:
        raise MemoryValidationError("memory_confidence_out_of_range")


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
