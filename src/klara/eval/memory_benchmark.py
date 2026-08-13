"""Fair memory retrieval matrix and public-benchmark execution contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
from time import perf_counter
from typing import Any

from klara.memory import MemoryKind, MemoryProvenance, MemoryScope, MemoryService, SQLiteMemoryRepository


RETRIEVAL_SYSTEMS = (
    "full_context",
    "recent",
    "lexical",
    "vector",
    "hybrid",
    "mem0_compatible",
)

PUBLIC_BENCHMARK_CONTRACTS = {
    "locomo": {
        "repository": "https://github.com/snap-research/locomo",
        "task": "very_long_term_conversational_qa",
        "status": "adapter_contract_ready_dataset_not_vendored",
    },
    "longmemeval": {
        "repository": "https://github.com/xiaowu0162/LongMemEval",
        "task": "extraction_multisession_update_temporal_abstention",
        "status": "adapter_contract_ready_dataset_not_vendored",
    },
    "memoryagentbench": {
        "repository": "https://github.com/HUST-AI-HYZ/MemoryAgentBench",
        "task": "retrieval_test_time_learning_long_range_conflict",
        "status": "adapter_contract_ready_dataset_not_vendored",
    },
    "beam": {
        "repository": "https://github.com/mohammadtavakoli78/BEAM",
        "task": "128k_to_10m_long_term_memory",
        "status": "hku_scale_only",
    },
}

COMPETITOR_CONTRACTS = {
    "mem0": {
        "repository": "https://github.com/mem0ai/memory-benchmarks",
        "adapter": "official_pipeline_required",
        "status": "not_executed",
    },
    "mem1": {
        "repository": "https://github.com/MIT-MI/MEM1",
        "adapter": "official_checkpoint_and_rollout_required",
        "status": "not_executed",
    },
}


@dataclass(frozen=True)
class MemoryRetrievalCase:
    case_id: str
    query: str
    expected_memory_ids: tuple[str, ...]
    at_time: str | None = None
    critical: bool = False


def run_retrieval_matrix(
    *,
    service: MemoryService,
    scope: MemoryScope,
    cases: list[MemoryRetrievalCase],
    limit: int = 5,
) -> dict[str, Any]:
    """Evaluate ablations with identical memories, cases, and retrieval budgets."""

    systems: dict[str, dict[str, Any]] = {}
    for mode in RETRIEVAL_SYSTEMS:
        started = perf_counter()
        rows = []
        for case in cases:
            hits = service.search(
                scope=scope,
                query=case.query,
                mode=mode,
                at_time=case.at_time,
                limit=limit,
            )
            returned = [hit.record.memory_id for hit in hits]
            expected = set(case.expected_memory_ids)
            selected = set(returned)
            true_positive = len(expected & selected)
            recall = true_positive / len(expected) if expected else 1.0
            precision = true_positive / len(selected) if selected else (1.0 if not expected else 0.0)
            rows.append(
                {
                    "case_id": case.case_id,
                    "recall_at_k": recall,
                    "precision_at_k": precision,
                    "top1_correct": bool(returned and returned[0] in expected),
                    "critical": case.critical,
                }
            )
        duration_ms = int((perf_counter() - started) * 1000)
        systems[mode] = {
            "cases": len(rows),
            "recall_at_k": _mean(row["recall_at_k"] for row in rows),
            "precision_at_k": _mean(row["precision_at_k"] for row in rows),
            "top1_accuracy": _mean(float(row["top1_correct"]) for row in rows),
            "critical_top1_accuracy": _mean(
                float(row["top1_correct"]) for row in rows if row["critical"]
            ),
            "latency_ms": duration_ms,
            "rows": rows,
        }
    return {
        "schema_version": "klara.memory-benchmark.v1",
        "same_answer_model": "not_applicable_retrieval_only_local_gate",
        "same_memory_corpus": True,
        "same_cases": True,
        "same_top_k": limit,
        "systems": systems,
        "public_benchmarks": PUBLIC_BENCHMARK_CONTRACTS,
        "competitors": COMPETITOR_CONTRACTS,
        "interpretation": (
            "This local gate validates retrieval ablations only. It does not claim Mem0/MEM1 "
            "or public benchmark superiority; those require official adapters and the same frozen answer model."
        ),
    }


def load_retrieval_cases(path: Path) -> list[MemoryRetrievalCase]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return [
        MemoryRetrievalCase(
            case_id=item["case_id"],
            query=item["query"],
            expected_memory_ids=tuple(item["expected_memory_ids"]),
            at_time=item.get("at_time"),
            critical=bool(item.get("critical", False)),
        )
        for item in value["cases"]
    ]


def fixture_service(
    path: Path, fixture: dict[str, Any]
) -> tuple[MemoryService, MemoryScope, dict[str, str]]:
    service = MemoryService(SQLiteMemoryRepository(path))
    scope = MemoryScope("benchmark", "benchmark-user", agent_id="klara")
    for item in fixture["memories"]:
        service.remember(
            scope=scope,
            content=item["content"],
            kind=MemoryKind(item["kind"]),
            provenance=MemoryProvenance(source_type="benchmark_fixture", actor_id="benchmark"),
            confidence=float(item.get("confidence", 1.0)),
            valid_from=item.get("valid_from"),
            valid_to=item.get("valid_to"),
            metadata={"fixture_id": item["memory_id"]},
        )
    records = service.list_records(scope=scope, include_inactive=True)
    remap = {record.metadata["fixture_id"]: record.memory_id for record in records}
    return service, scope, remap


def run_fixture_matrix(fixture_path: Path, database_path: Path) -> dict[str, Any]:
    """Run the checked-in retrieval fixture with generated-id remapping."""

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    service, scope, remap = fixture_service(database_path, fixture)
    cases = [
        MemoryRetrievalCase(
            case_id=item["case_id"],
            query=item["query"],
            expected_memory_ids=tuple(remap[value] for value in item["expected_memory_ids"]),
            at_time=item.get("at_time"),
            critical=bool(item.get("critical", False)),
        )
        for item in fixture["cases"]
    ]
    report = run_retrieval_matrix(service=service, scope=scope, cases=cases)
    report["fixture_sha256"] = file_sha256(fixture_path)
    return report


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mean(values) -> float:
    items = list(values)
    return round(sum(items) / len(items), 6) if items else 1.0
