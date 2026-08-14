"""License-aware adapters for public long-term-memory benchmark datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any, Iterable

from klara.memory import (
    MemoryKind,
    MemoryProvenance,
    MemoryScope,
    MemoryService,
    SQLiteMemoryRepository,
)
from klara.memory.models import MemoryRecord, MemorySensitivity, MemoryStatus
from klara.memory.retrieval import rank_memories


SCHEMA_VERSION = "klara.public-memory-benchmark.v1"
ADAPTER_VERSION = "klara.locomo-retrieval-adapter.v1"
LONGMEMEVAL_ADAPTER_VERSION = "klara.longmemeval-oracle-adapter.v1"
LONGMEMEVAL_DATA_SHA256 = "821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c"
MEMORY_AGENT_BENCH_REVISION = "7ea066982b140a19337e17e60d45d4076e042faf"
MEMORY_AGENT_BENCH_FILES = {
    "Accurate_Retrieval": {
        "rows": 22,
        "sha256": "56c3cd80fb6731a3e53cd1a6be3148f54df60ff2d290ee50e28f8acebf9655c1",
    },
    "Test_Time_Learning": {
        "rows": 6,
        "sha256": "5338753be48f925d03318eed66117286e3489025fabe050a547bd086cd7d79c0",
    },
    "Long_Range_Understanding": {
        "rows": 110,
        "sha256": "5ab175461954db67770d4a4cb69e569b513ebb96aceb9ee79b57f67488bcd539",
    },
    "Conflict_Resolution": {
        "rows": 8,
        "sha256": "24d5c3f09ce0ce15625cb9f8a98f44f0d864ca6c94d7b4ad04eb697ca3a5ff45",
    },
}
LOCOMO_COMMIT = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
LOCOMO_DATA_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
LOCOMO_LICENSE = "CC-BY-NC-4.0"
RETRIEVAL_MODES = (
    "recent",
    "lexical",
    "vector",
    "semantic_recency",
    "hybrid",
)


@dataclass(frozen=True)
class LocomoTurn:
    conversation_index: int
    dia_id: str
    content: str
    occurred_at: str | None
    turn_index: int


@dataclass(frozen=True)
class LocomoQuestion:
    conversation_index: int
    question_index: int
    question: str
    answer: str
    evidence_ids: tuple[str, ...]
    category: str

    @property
    def case_id(self) -> str:
        return f"locomo-{self.conversation_index:02d}-{self.question_index:03d}"


def inspect_public_source(
    repository_root: Path,
    *,
    expected_commit: str,
    required_paths: Iterable[str],
) -> dict[str, Any]:
    """Verify one ignored third-party checkout without importing its code."""

    head_path = repository_root / ".git" / "HEAD"
    actual_commit = _resolve_git_head(repository_root) if head_path.exists() else None
    paths = {
        relative: {
            "exists": (repository_root / relative).is_file(),
            "sha256": _file_sha256(repository_root / relative)
            if (repository_root / relative).is_file()
            else None,
        }
        for relative in required_paths
    }
    return {
        "path": str(repository_root),
        "expected_commit": expected_commit,
        "actual_commit": actual_commit,
        "commit_matches": actual_commit == expected_commit,
        "required_paths": paths,
        "passed": actual_commit == expected_commit
        and all(item["exists"] for item in paths.values()),
    }


def load_locomo(path: Path) -> tuple[list[LocomoTurn], list[LocomoQuestion], dict[str, Any]]:
    """Load the official LoCoMo JSON while preserving its QA/evidence labels."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != 10:
        raise ValueError("locomo_expected_ten_conversations")
    turns: list[LocomoTurn] = []
    questions: list[LocomoQuestion] = []
    category_counts: dict[str, int] = {}
    for conversation_index, entry in enumerate(payload):
        conversation = entry.get("conversation")
        qa = entry.get("qa")
        if not isinstance(conversation, dict) or not isinstance(qa, list):
            raise ValueError("locomo_invalid_entry")
        evidence_universe: set[str] = set()
        session_keys = sorted(
            (
                key
                for key, value in conversation.items()
                if key.startswith("session_")
                and not key.endswith("_date_time")
                and isinstance(value, list)
            ),
            key=lambda value: int(value.removeprefix("session_")),
        )
        conversation_turn_index = 0
        for key in session_keys:
            session = conversation[key]
            if not isinstance(session, list):
                continue
            date_value = conversation.get(f"{key}_date_time")
            occurred_at = _locomo_time(date_value) if isinstance(date_value, str) else None
            for turn in session:
                if not isinstance(turn, dict):
                    raise ValueError("locomo_invalid_turn")
                dia_id = str(turn.get("dia_id", "")).strip()
                text = str(turn.get("text", "")).strip()
                if not dia_id or not text:
                    continue
                speaker = str(turn.get("speaker", "")).strip()
                image = str(turn.get("blip_caption", "")).strip()
                content = f"{speaker}: {text}" if speaker else text
                if image:
                    content = f"{content} [Image: {image}]"
                turns.append(
                    LocomoTurn(
                        conversation_index=conversation_index,
                        dia_id=dia_id,
                        content=content,
                        occurred_at=occurred_at,
                        turn_index=conversation_turn_index,
                    )
                )
                conversation_turn_index += 1
                evidence_universe.add(dia_id)
        for question_index, item in enumerate(qa):
            if not isinstance(item, dict):
                raise ValueError("locomo_invalid_question")
            evidence = tuple(str(value) for value in item.get("evidence", []) if str(value))
            if not evidence or not set(evidence).issubset(evidence_universe):
                continue
            category = str(item.get("category", "unknown"))
            category_counts[category] = category_counts.get(category, 0) + 1
            questions.append(
                LocomoQuestion(
                    conversation_index=conversation_index,
                    question_index=question_index,
                    question=str(item.get("question", "")).strip(),
                    answer=str(item.get("answer", "")).strip(),
                    evidence_ids=evidence,
                    category=category,
                )
            )
    if not turns or not questions:
        raise ValueError("locomo_empty_adapter_output")
    return turns, questions, {
        "conversations": len(payload),
        "turns": len(turns),
        "eligible_questions": len(questions),
        "category_counts": dict(sorted(category_counts.items())),
    }


def select_locomo_questions(
    questions: list[LocomoQuestion],
    *,
    per_conversation: int = 10,
    selection_offset: int = 0,
    scored_categories: frozenset[str] = frozenset({"1", "2", "3", "4"}),
) -> list[LocomoQuestion]:
    """Freeze a balanced subset using LoCoMo's official scored categories."""

    if selection_offset < 0:
        raise ValueError("locomo_selection_offset_must_be_non_negative")

    grouped: dict[int, list[LocomoQuestion]] = {}
    for question in questions:
        if question.category not in scored_categories:
            continue
        grouped.setdefault(question.conversation_index, []).append(question)
    selected: list[LocomoQuestion] = []
    for conversation_index in sorted(grouped):
        candidates = sorted(
            grouped[conversation_index],
            key=lambda item: (
                hashlib.sha256(item.case_id.encode("utf-8")).hexdigest(),
                item.case_id,
            ),
        )
        selected.extend(
            candidates[selection_offset : selection_offset + per_conversation]
        )
    return sorted(selected, key=lambda item: item.case_id)


def run_locomo_retrieval(
    dataset_path: Path,
    database_path: Path,
    *,
    per_conversation: int = 10,
    top_k: int = 5,
) -> dict[str, Any]:
    """Run evidence-ID retrieval only; answer generation is a separate live gate."""

    if _file_sha256(dataset_path) != LOCOMO_DATA_SHA256:
        raise ValueError("locomo_dataset_hash_mismatch")
    turns, all_questions, dataset_stats = load_locomo(dataset_path)
    questions = select_locomo_questions(
        all_questions, per_conversation=per_conversation
    )
    service = MemoryService(SQLiteMemoryRepository(database_path))
    scopes: dict[int, MemoryScope] = {}
    corpora: dict[int, list[MemoryRecord]] = {}
    fixed_time = "2026-01-01T00:00:00+00:00"
    for turn in turns:
        scope = scopes.setdefault(
            turn.conversation_index,
            MemoryScope(
                "locomo-public",
                f"conversation-{turn.conversation_index}",
                agent_id="klara",
            ),
        )
        corpora.setdefault(turn.conversation_index, []).append(
            MemoryRecord(
                memory_id=turn.dia_id,
                scope=scope,
                content=turn.content,
                kind=MemoryKind.EPISODIC,
                sensitivity=MemorySensitivity.STANDARD,
                provenance=MemoryProvenance(
                source_type="locomo_public_benchmark",
                actor_id="benchmark-adapter",
                source_id=turn.dia_id,
            ),
                created_at=turn.occurred_at or fixed_time,
                updated_at=turn.occurred_at or fixed_time,
                valid_from=turn.occurred_at,
                status=MemoryStatus.ACTIVE,
                metadata={
                    "locomo_dia_id": turn.dia_id,
                    "conversation_turn_index": turn.turn_index,
                },
            )
        )

    systems: dict[str, Any] = {}
    for mode in RETRIEVAL_MODES:
        started = perf_counter()
        rows = []
        for question in questions:
            hits = rank_memories(
                corpora[question.conversation_index],
                query=question.question,
                mode=mode,
                limit=top_k,
                now=fixed_time,
            )
            returned = [hit.record.memory_id for hit in hits]
            expected = set(question.evidence_ids)
            found = expected.intersection(returned)
            reciprocal_rank = next(
                (1.0 / index for index, value in enumerate(returned, start=1) if value in expected),
                0.0,
            )
            rows.append(
                {
                    "case_id": question.case_id,
                    "category": question.category,
                    "evidence_count": len(expected),
                    "retrieved_count": len(returned),
                    "evidence_recall_at_k": len(found) / len(expected),
                    "evidence_precision_at_k": len(found) / len(returned) if returned else 0.0,
                    "evidence_hit_at_k": bool(found),
                    "reciprocal_rank": reciprocal_rank,
                }
            )
        systems[mode] = _aggregate_rows(rows, int((perf_counter() - started) * 1000))

    hybrid = systems["hybrid"]
    strongest_ablation_recall = max(
        systems[name]["evidence_recall_at_k"]
        for name in RETRIEVAL_MODES
        if name != "hybrid"
    )
    checks = {
        "official_dataset_hash": _file_sha256(dataset_path) == LOCOMO_DATA_SHA256,
        "balanced_ten_by_ten_subset": len(questions) == 10 * per_conversation,
        "all_evidence_labels_resolve": all(row["evidence_count"] > 0 for row in systems["hybrid"]["rows"]),
        "hybrid_recall_at_5_at_least_0_50": hybrid["evidence_recall_at_k"] >= 0.50,
        "hybrid_hit_at_5_at_least_0_65": hybrid["evidence_hit_at_k"] >= 0.65,
        "hybrid_not_below_strongest_ablation_by_more_than_0_03": hybrid["evidence_recall_at_k"] + 0.03 >= strongest_ablation_recall,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "benchmark": "LoCoMo",
        "task": "gold_evidence_id_retrieval",
        "source": {
            "repository": "https://github.com/snap-research/locomo",
            "commit": LOCOMO_COMMIT,
            "dataset_sha256": LOCOMO_DATA_SHA256,
            "license": LOCOMO_LICENSE,
        },
        "selection": {
            "algorithm": "official scored categories 1-4; sha256(case_id), first N per conversation",
            "scored_categories": ["1", "2", "3", "4"],
            "per_conversation": per_conversation,
            "selected_questions": len(questions),
            "selected_case_ids_sha256": _stable_hash([item.case_id for item in questions]),
        },
        "dataset": dataset_stats,
        "same_corpus_queries_top_k": True,
        "top_k": top_k,
        "systems": systems,
        "checks": checks,
        "limitations": [
            "This run measures retrieval of official gold evidence IDs, not end-to-end answer quality.",
            "The local semantic signal is a dependency-free hashed character-ngram vector, not a learned embedding model.",
            "LoCoMo is CC-BY-NC-4.0 and is kept outside the Git repository.",
        ],
        "passed": all(checks.values()),
    }


def evaluate_locomo_checkout(checkout: Path) -> dict[str, Any]:
    """Convenience entrypoint that never writes into the third-party checkout."""

    source = inspect_public_source(
        checkout,
        expected_commit=LOCOMO_COMMIT,
        required_paths=("LICENSE.txt", "data/locomo10.json"),
    )
    if not source["passed"]:
        return {
            "schema_version": SCHEMA_VERSION,
            "benchmark": "LoCoMo",
            "source_inspection": source,
            "passed": False,
        }
    with TemporaryDirectory(prefix="klara-locomo-") as temporary:
        report = run_locomo_retrieval(
            checkout / "data" / "locomo10.json",
            Path(temporary) / "locomo.sqlite3",
        )
    report["source_inspection"] = source
    report["passed"] = report["passed"] and source["passed"]
    return report


def run_longmemeval_oracle_contract(
    dataset_path: Path,
    *,
    sample_size: int = 60,
) -> dict[str, Any]:
    """Validate the cleaned oracle split and its official evidence-session contract."""

    dataset_hash = _file_sha256(dataset_path)
    if dataset_hash != LONGMEMEVAL_DATA_SHA256:
        raise ValueError("longmemeval_dataset_hash_mismatch")
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != 500:
        raise ValueError("longmemeval_expected_five_hundred_questions")
    selected = sorted(
        payload,
        key=lambda item: (
            hashlib.sha256(str(item.get("question_id", "")).encode("utf-8")).hexdigest(),
            str(item.get("question_id", "")),
        ),
    )[:sample_size]
    rows = []
    for item in selected:
        question_id = str(item.get("question_id", "")).strip()
        sessions = item.get("haystack_sessions")
        session_ids = item.get("haystack_session_ids")
        answer_session_ids = item.get("answer_session_ids")
        dates = item.get("haystack_dates")
        if not question_id or not all(
            isinstance(value, list)
            for value in (sessions, session_ids, answer_session_ids, dates)
        ):
            raise ValueError("longmemeval_invalid_question")
        if not (len(sessions) == len(session_ids) == len(dates)):
            raise ValueError("longmemeval_session_alignment_mismatch")
        answer_ids = {str(value) for value in answer_session_ids}
        available_ids = {str(value) for value in session_ids}
        content_nonempty = all(
            isinstance(session, list)
            and any(
                isinstance(message, dict)
                and isinstance(message.get("content"), str)
                and bool(message["content"].strip())
                for message in session
            )
            for session in sessions
        )
        rows.append(
            {
                "question_id": question_id,
                "question_type": str(item.get("question_type", "")),
                "session_count": len(sessions),
                "answer_session_count": len(answer_ids),
                "answer_sessions_present": answer_ids.issubset(available_ids),
                "session_content_nonempty": content_nonempty,
                "answer_present": bool(str(item.get("answer", "")).strip()),
            }
        )
    type_counts: dict[str, int] = {}
    for row in rows:
        question_type = row["question_type"]
        type_counts[question_type] = type_counts.get(question_type, 0) + 1
    checks = {
        "official_dataset_hash": dataset_hash == LONGMEMEVAL_DATA_SHA256,
        "official_question_count_500": len(payload) == 500,
        "frozen_sample_size": len(rows) == sample_size,
        "answer_session_ids_resolve": all(row["answer_sessions_present"] for row in rows),
        "session_content_nonempty": all(row["session_content_nonempty"] for row in rows),
        "answers_nonempty": all(row["answer_present"] for row in rows),
        "multiple_capability_types_present": len(type_counts) >= 5,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": LONGMEMEVAL_ADAPTER_VERSION,
        "benchmark": "LongMemEval",
        "task": "cleaned_oracle_adapter_contract",
        "source": {
            "repository": "https://github.com/xiaowu0162/LongMemEval",
            "commit": "9e0b455f4ef0e2ab8f2e582289761153549043fc",
            "dataset": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned",
            "dataset_sha256": LONGMEMEVAL_DATA_SHA256,
            "license": "MIT",
        },
        "selection": {
            "algorithm": "sha256(question_id), first N",
            "sample_size": len(rows),
            "question_ids_sha256": _stable_hash([row["question_id"] for row in rows]),
            "question_type_counts": dict(sorted(type_counts.items())),
        },
        "checks": checks,
        "rows": rows,
        "limitations": [
            "The oracle split already contains only answer-bearing evidence sessions; it cannot measure retrieval quality.",
            "This contract run validates official labels and adapter alignment, not answer accuracy.",
            "End-to-end LongMemEval requires the same frozen answer model and official judge and is a separate paid/live gate.",
        ],
        "passed": all(checks.values()),
    }


def run_memory_agent_bench_contract(cache_root: Path) -> dict[str, Any]:
    """Validate all four official splits without executing answer-model calls."""

    try:
        from datasets import load_dataset
    except ImportError as exc:  # pragma: no cover - optional public benchmark env
        raise RuntimeError("datasets_dependency_required") from exc
    split_reports: dict[str, Any] = {}
    for split, contract in MEMORY_AGENT_BENCH_FILES.items():
        dataset = load_dataset(
            "ai-hyz/MemoryAgentBench",
            split=split,
            revision=MEMORY_AGENT_BENCH_REVISION,
            cache_dir=str(cache_root),
        )
        sources: dict[str, int] = {}
        question_count = 0
        alignment_passed = True
        for row in dataset:
            questions = row.get("questions")
            answers = row.get("answers")
            metadata = row.get("metadata")
            if not isinstance(questions, list) or not isinstance(answers, list) or not isinstance(metadata, dict):
                alignment_passed = False
                continue
            question_count += len(questions)
            if len(questions) != len(answers):
                alignment_passed = False
            source = str(metadata.get("source", "unknown"))
            sources[source] = sources.get(source, 0) + 1
        split_reports[split] = {
            "rows": len(dataset),
            "expected_rows": contract["rows"],
            "questions": question_count,
            "sources": dict(sorted(sources.items())),
            "official_file_sha256": contract["sha256"],
            "question_answer_alignment": alignment_passed,
            "passed": len(dataset) == contract["rows"] and alignment_passed and question_count > 0,
        }
    checks = {
        "official_revision_pinned": len(MEMORY_AGENT_BENCH_REVISION) == 40,
        "all_four_competencies_present": set(split_reports) == set(MEMORY_AGENT_BENCH_FILES),
        "all_split_contracts_pass": all(item["passed"] for item in split_reports.values()),
        "official_row_count_146": sum(item["rows"] for item in split_reports.values()) == 146,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": "klara.memory-agent-bench-adapter.v1",
        "benchmark": "MemoryAgentBench",
        "task": "official_dataset_contract",
        "source": {
            "repository": "https://github.com/HUST-AI-HYZ/MemoryAgentBench",
            "repository_commit": "455306dcabc3842526eb83cd4e225e5d486c5c5d",
            "dataset": "https://huggingface.co/datasets/ai-hyz/MemoryAgentBench",
            "dataset_revision": MEMORY_AGENT_BENCH_REVISION,
            "license": "MIT",
        },
        "splits": split_reports,
        "checks": checks,
        "limitations": [
            "This run validates all official split schemas, sources, and labels; it is not an answer-accuracy result.",
            "Official execution needs incremental memory ingestion and the same frozen answer model for Klara and competitors.",
            "The four aggregate capabilities must not be reduced to retrieval-only metrics.",
        ],
        "passed": all(checks.values()),
    }
def _aggregate_rows(rows: list[dict[str, Any]], latency_ms: int) -> dict[str, Any]:
    count = len(rows)
    return {
        "cases": count,
        "evidence_recall_at_k": _mean(row["evidence_recall_at_k"] for row in rows),
        "evidence_precision_at_k": _mean(row["evidence_precision_at_k"] for row in rows),
        "evidence_hit_at_k": _mean(float(row["evidence_hit_at_k"]) for row in rows),
        "mean_reciprocal_rank": _mean(row["reciprocal_rank"] for row in rows),
        "latency_ms": latency_ms,
        "rows": rows,
    }


def _mean(values: Iterable[float]) -> float:
    materialized = tuple(values)
    return round(sum(materialized) / len(materialized), 6) if materialized else 0.0


def _locomo_time(value: str) -> str | None:
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC).isoformat()
        except ValueError:
            continue
    return None


def _resolve_git_head(root: Path) -> str | None:
    import subprocess

    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and len(value) == 40 else None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
