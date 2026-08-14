from __future__ import annotations

from dataclasses import dataclass

from klara.memory import (
    ExtractedMemoryFact,
    MemoryFormationMode,
    MemoryFormationService,
    MemoryKind,
    MemoryScope,
    MemorySensitivity,
    MemoryService,
    SQLiteMemoryRepository,
)


@dataclass
class _Extractor:
    facts: tuple[ExtractedMemoryFact, ...]
    calls: int = 0

    def extract(self, *, user_content: str, assistant_content: str):
        self.calls += 1
        return self.facts


def _fact(
    content: str,
    *,
    confidence: float = 0.95,
    sensitivity: MemorySensitivity = MemorySensitivity.STANDARD,
) -> ExtractedMemoryFact:
    return ExtractedMemoryFact(
        content=content,
        kind=MemoryKind.USER_PREFERENCE,
        sensitivity=sensitivity,
        confidence=confidence,
        attributed_to="user",
        entities=("Klara",),
    )


def test_review_mode_never_makes_unreviewed_fact_retrievable(tmp_path) -> None:
    memory = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    extractor = _Extractor((_fact("The user prefers concise answers."),))
    service = MemoryFormationService(memory, extractor, mode=MemoryFormationMode.REVIEW)
    scope = MemoryScope("tenant", "user", "agent")

    result = service.capture_turn(
        scope=scope,
        user_content="Please keep answers concise.",
        assistant_content="I will.",
        source_id="run-1",
    )

    assert result.proposed == 1 and result.committed == 0
    assert memory.search(scope=scope, query="concise") == []


def test_auto_safe_commits_only_high_confidence_standard_facts(tmp_path) -> None:
    memory = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    extractor = _Extractor(
        (
            _fact("The user prefers concise answers."),
            _fact("The user mentioned a health condition.", sensitivity=MemorySensitivity.SENSITIVE),
            _fact("The user may prefer tables.", confidence=0.6),
        )
    )
    service = MemoryFormationService(memory, extractor, mode=MemoryFormationMode.AUTO_SAFE)
    scope = MemoryScope("tenant", "user", "agent")

    result = service.capture_turn(
        scope=scope, user_content="turn", assistant_content="answer", source_id="run-2"
    )

    assert result.committed == 1
    assert result.proposed == 2
    assert [record.content for record in memory.list_records(scope=scope)] == [
        "The user prefers concise answers."
    ]


def test_formation_is_single_pass_bounded_and_deduplicated(tmp_path) -> None:
    memory = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    extractor = _Extractor(tuple(_fact(f"fact {index}") for index in range(10)))
    service = MemoryFormationService(memory, extractor, mode=MemoryFormationMode.AUTO_SAFE)
    scope = MemoryScope("tenant", "user", "agent")

    first = service.capture_turn(
        scope=scope, user_content="turn", assistant_content="answer", source_id="run-3"
    )
    second = service.capture_turn(
        scope=scope, user_content="turn", assistant_content="answer", source_id="run-4"
    )

    assert extractor.calls == 2
    assert first.extracted == 8 and first.committed == 8
    assert second.duplicates_skipped == 8 and second.committed == 0


def test_disabled_mode_does_not_call_model(tmp_path) -> None:
    memory = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.sqlite3"))
    extractor = _Extractor((_fact("unused"),))
    service = MemoryFormationService(memory, extractor, mode=MemoryFormationMode.DISABLED)

    result = service.capture_turn(
        scope=MemoryScope("tenant", "user", "agent"),
        user_content="turn",
        assistant_content="answer",
        source_id="run-5",
    )

    assert result.extracted == 0
    assert extractor.calls == 0
