"""Machine-check Chapter 10 governed, tenant-scoped long-term memory."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from apps.api.routes.memory import list_memories
from apps.api.services.run_event_projector import RunEventProjector
from klara.core.events import KlaraEvent
from klara.eval.memory_benchmark import run_fixture_matrix
from klara.memory import (
    MemoryKind,
    MemoryNotFoundError,
    MemoryProvenance,
    MemoryScope,
    MemoryService,
    SQLiteMemoryRepository,
)


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter10-memory.v1"


def evaluate_chapter10(root: Path) -> dict[str, Any]:
    """Exercise lifecycle, isolation, deletion, retrieval ablations, API, and UI."""

    with TemporaryDirectory(prefix="klara-ch10-") as temporary:
        temp = Path(temporary)
        service = MemoryService(SQLiteMemoryRepository(temp / "memory.sqlite3"))
        owner = MemoryScope("tenant-a", "user-a", agent_id="klara")
        other_tenant = MemoryScope("tenant-b", "user-a", agent_id="klara")
        private_phrase = "Private sea-glass preference"
        first = service.remember(
            scope=owner,
            content=private_phrase,
            kind=MemoryKind.USER_PREFERENCE,
            provenance=MemoryProvenance(
                source_type="explicit_gate",
                actor_id="user-a",
                source_id="run-gate",
            ),
        )
        updated = service.update(
            scope=owner,
            memory_id=first.memory_id,
            content="Private amber preference",
            actor_id="user-a",
        )
        current_hits = service.search(scope=owner, query="amber preference")
        historical_hits = service.search(
            scope=owner,
            query="sea glass preference",
            at_time=first.created_at,
        )
        isolated_hits = service.search(scope=other_tenant, query="preference")
        cross_tenant_error = ""
        try:
            service.delete(
                scope=other_tenant,
                memory_id=updated.memory_id,
                actor_id="user-a",
            )
        except MemoryNotFoundError as exc:
            cross_tenant_error = str(exc)
        receipt = service.delete(
            scope=owner,
            memory_id=updated.memory_id,
            actor_id="user-a",
        )
        api_payload = list_memories(service, owner)
        audit_dump = json.dumps(
            [event.to_owner_dict() for event in service.audit(scope=owner)],
            ensure_ascii=False,
        )
        projected = RunEventProjector().project(
            KlaraEvent(
                type="memory.retrieved",
                run_id="run-gate",
                payload={
                    "memory_id": first.memory_id,
                    "result_count": 1,
                    "content": private_phrase,
                    "query": "private query",
                },
            )
        )[0]
        projection_dump = json.dumps(projected.payload, ensure_ascii=False)
        benchmark = run_fixture_matrix(
            root / "tests/fixtures/memory/ch10_retrieval_cases.json",
            temp / "benchmark.sqlite3",
        )

    frontend = (root / "apps/web/src/components/MemoryManager.tsx").read_text(
        encoding="utf-8"
    )
    route_source = (root / "apps/api/routes/memory.py").read_text(encoding="utf-8")
    hybrid = benchmark["systems"]["hybrid"]
    checks = {
        "stage_manifest_exists": (
            root / "config/stages/ch10-memory.manifest.json"
        ).exists(),
        "five_memory_kinds_declared": len(MemoryKind) == 5,
        "tenant_read_isolation": isolated_hits == [],
        "tenant_mutation_isolation": cross_tenant_error == "memory_not_found",
        "current_fact_supersedes_old_fact": bool(current_hits)
        and current_hits[0].record.memory_id == updated.memory_id,
        "historical_query_recovers_old_fact": bool(historical_hits)
        and historical_hits[0].record.memory_id == first.memory_id,
        "hard_delete_is_verified": receipt["deletion_verified"] is True
        and receipt["raw_content_occurrences"] == 0,
        "audit_uses_hash_not_raw_deleted_content": "Private amber preference"
        not in audit_dump,
        "api_is_owner_scoped": api_payload["schema_version"]
        == "klara.memory-list.v1"
        and all(item["scope"]["tenant_id"] == "tenant-a" for item in api_payload["records"]),
        "public_projection_hides_content_and_query": private_phrase
        not in projection_dump
        and "private query" not in projection_dump
        and projected.payload["content_exposed"] is False,
        "hybrid_retrieval_critical_top1_is_perfect": hybrid[
            "critical_top1_accuracy"
        ]
        == 1.0,
        "retrieval_ablation_matrix_is_complete": set(benchmark["systems"])
        == {"full_context", "recent", "lexical", "vector", "hybrid", "mem0_compatible"},
        "competitors_are_not_falsely_claimed": all(
            value["status"] == "not_executed"
            for value in benchmark["competitors"].values()
        ),
        "frontend_has_search_provenance_update_forget_delete": all(
            term in frontend
            for term in (
                "Search content or provenance",
                "Source:",
                "Edit memory",
                "Forget",
                "Delete memory",
                "deletion_verified",
            )
        ),
        "api_exposes_governed_lifecycle": all(
            term in route_source
            for term in ("create_memory", "search_memories", "update_memory", "forget_memory", "delete_memory")
        ),
        "bilingual_tutorial_exists": all(
            (root / path).exists()
            for path in (
                "docs/chapters/ch10-memory-system.md",
                "docs/chapters/ch10-memory-system.en.md",
            )
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch10-memory",
        "gate_kind": "deterministic_memory_lifecycle_and_retrieval_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "memory_kind_count": len(MemoryKind),
            "tenant_isolation_failure_count": 0
            if isolated_hits == [] and cross_tenant_error == "memory_not_found"
            else 1,
            "raw_deleted_content_occurrences": receipt["raw_content_occurrences"],
            "hybrid_top1_accuracy": hybrid["top1_accuracy"],
            "hybrid_critical_top1_accuracy": hybrid["critical_top1_accuracy"],
        },
        "retrieval_matrix": benchmark,
        "deletion_receipt": receipt,
        "interpretation": (
            "Passing proves the repository-native memory lifecycle, owner partition, "
            "temporal supersession, hard-delete proof, trace privacy, UI controls, and a "
            "small deterministic retrieval-ablation gate. It does not claim end-to-end "
            "LoCoMo, LongMemEval, MemoryAgentBench, BEAM, Mem0, or MEM1 superiority; those "
            "remain frozen same-model benchmark work before Agent Product Freeze."
        ),
        "passed": all(checks.values()),
    }


def render_chapter10_markdown(
    report: dict[str, Any], *, language: str = "zh"
) -> str:
    """Render one report object as Chinese-first and English-mirror Markdown."""

    english = language == "en"
    title = "Chapter 10 Memory Gate" if english else "Chapter 10 Memory 门禁"
    toggle = (
        "Language: [Chinese](./ch10-memory.md) | English"
        if english
        else "语言：中文 | [English](./ch10-memory.en.md)"
    )
    lines = [
        f"# {title}",
        "",
        toggle,
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Gate kind' if english else '门禁类型'}: `{report['gate_kind']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        "",
        f"## {'Acceptance Checks' if english else '验收检查'}",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {key} | {'PASS' if value else 'FAIL'} |"
        for key, value in sorted(report["checks"].items())
    )
    lines.extend(
        [
            "",
            f"## {'Retrieval Ablations' if english else '检索消融'}",
            "",
            f"| {'System' if english else '系统'} | Top-1 | Critical Top-1 | Recall@5 | Precision@5 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, value in report["retrieval_matrix"]["systems"].items():
        lines.append(
            f"| {name} | {value['top1_accuracy']:.3f} | "
            f"{value['critical_top1_accuracy']:.3f} | {value['recall_at_k']:.3f} | "
            f"{value['precision_at_k']:.3f} |"
        )
    lines.extend(
        [
            "",
            f"## {'Interpretation Boundary' if english else '解释边界'}",
            "",
            report["interpretation"]
            if english
            else (
                "通过表示仓库原生 Memory 生命周期、所有者分区、时间冲突处理、硬删除证明、"
                "公开轨迹隐私、管理界面和小型确定性检索消融门禁成立。它不表示已经在端到端 "
                "LoCoMo、LongMemEval、MemoryAgentBench、BEAM，或与 Mem0、MEM1 的同模型对比中胜出；"
                "这些仍是 Agent Product Freeze 前必须执行的冻结基准工作。"
            ),
            "",
        ]
    )
    return "\n".join(lines)
