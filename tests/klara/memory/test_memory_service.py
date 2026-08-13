from __future__ import annotations

from pathlib import Path

import pytest

from klara.memory import (
    MemoryKind,
    MemoryNotFoundError,
    MemoryProvenance,
    MemoryScope,
    MemorySensitivity,
    MemoryService,
    MemoryStatus,
    SQLiteMemoryRepository,
)


def service(tmp_path: Path) -> MemoryService:
    return MemoryService(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))


def provenance(actor: str = "user-a") -> MemoryProvenance:
    return MemoryProvenance(source_type="explicit_test", actor_id=actor)


def test_remember_search_update_temporal_and_delete(tmp_path: Path) -> None:
    memory = service(tmp_path)
    scope = MemoryScope("tenant-a", "user-a", agent_id="klara")
    first = memory.remember(
        scope=scope,
        content="I prefer dark mode for the editor",
        kind=MemoryKind.USER_PREFERENCE,
        sensitivity=MemorySensitivity.PERSONAL,
        provenance=provenance(),
    )

    hits = memory.search(scope=scope, query="editor theme preference")
    assert [hit.record.memory_id for hit in hits] == [first.memory_id]
    assert hits[0].record.provenance.source_type == "explicit_test"

    updated = memory.update(
        scope=scope,
        memory_id=first.memory_id,
        content="I prefer light mode for the editor",
        actor_id="user-a",
    )
    assert memory.list_records(scope=scope) == [updated]
    historical = memory.search(
        scope=scope,
        query="dark mode",
        at_time=first.created_at,
    )
    assert historical[0].record.memory_id == first.memory_id
    assert memory.repository.get_record(scope, first.memory_id).status is MemoryStatus.SUPERSEDED

    receipt = memory.delete(scope=scope, memory_id=updated.memory_id, actor_id="user-a")
    assert receipt["deletion_verified"] is True
    assert receipt["raw_content_occurrences"] == 0
    assert memory.search(scope=scope, query="light mode") == []


def test_tenant_isolation_fails_closed_for_read_update_and_delete(tmp_path: Path) -> None:
    memory = service(tmp_path)
    owner = MemoryScope("tenant-a", "user-a")
    intruder = MemoryScope("tenant-b", "user-a")
    record = memory.remember(
        scope=owner,
        content="tenant-a private launch date",
        kind=MemoryKind.STABLE_FACT,
        provenance=provenance(),
    )

    assert memory.search(scope=intruder, query="launch date") == []
    for operation in (
        lambda: memory.update(
            scope=intruder,
            memory_id=record.memory_id,
            content="changed",
            actor_id="user-a",
        ),
        lambda: memory.forget(scope=intruder, memory_id=record.memory_id, actor_id="user-a"),
        lambda: memory.delete(scope=intruder, memory_id=record.memory_id, actor_id="user-a"),
    ):
        with pytest.raises(MemoryNotFoundError, match="memory_not_found"):
            operation()


def test_automatic_candidate_requires_review_and_rejection_purges_content(tmp_path: Path) -> None:
    memory = service(tmp_path)
    scope = MemoryScope("tenant-a", "user-a")
    candidate = memory.propose_candidate(
        scope=scope,
        content="Maybe the user likes oolong tea",
        kind=MemoryKind.USER_PREFERENCE,
        sensitivity=MemorySensitivity.PERSONAL,
        provenance=MemoryProvenance(source_type="automatic_candidate", actor_id="klara"),
        confidence=0.61,
    )
    assert memory.search(scope=scope, query="oolong") == []

    assert memory.review_candidate(
        scope=scope,
        candidate_id=candidate.candidate_id,
        approve=False,
        actor_id="user-a",
    ) is None
    assert memory.repository.raw_content_occurrences(candidate.content) == 0

    approved = memory.propose_candidate(
        scope=scope,
        content="The user prefers concise status updates",
        kind=MemoryKind.USER_PREFERENCE,
        sensitivity=MemorySensitivity.STANDARD,
        provenance=MemoryProvenance(source_type="automatic_candidate", actor_id="klara"),
        confidence=0.9,
    )
    record = memory.review_candidate(
        scope=scope,
        candidate_id=approved.candidate_id,
        approve=True,
        actor_id="user-a",
    )
    assert record is not None
    assert memory.search(scope=scope, query="status updates")[0].record.memory_id == record.memory_id


def test_forget_ttl_export_and_exact_duplicate_consolidation(tmp_path: Path) -> None:
    memory = service(tmp_path)
    scope = MemoryScope("tenant-a", "user-a")
    first = memory.remember(
        scope=scope,
        content="Klara should answer in Chinese",
        kind=MemoryKind.AGENT_LEARNING,
        provenance=provenance(),
    )
    duplicate = memory.remember(
        scope=scope,
        content="  Klara should answer in Chinese  ",
        kind=MemoryKind.AGENT_LEARNING,
        provenance=provenance(),
        confidence=0.8,
    )
    expired = memory.remember(
        scope=scope,
        content="temporary task marker",
        kind=MemoryKind.TASK,
        provenance=provenance(),
        ttl_seconds=1,
    )
    consolidated = memory.consolidate(scope=scope, actor_id="user-a")
    assert consolidated["duplicates_superseded"] == 1
    assert memory.forget(scope=scope, memory_id=first.memory_id, actor_id="user-a").status is MemoryStatus.FORGOTTEN
    exported = memory.export(scope=scope)
    assert exported["schema_version"] == "klara.memory-export.v1"
    assert {item["memory_id"] for item in exported["records"]} == {
        first.memory_id,
        duplicate.memory_id,
        expired.memory_id,
    }
    assert all("content" not in event["details"] for event in exported["audit"])
