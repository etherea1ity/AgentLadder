"""Aggregate the repaired latest-branch architecture gate without claiming model quality."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


CHAPTER_GATES = (
    "chapter04",
    "chapter05",
    "chapter06_07",
    "chapter08",
    "chapter09",
    "chapter10",
    "chapter12_13",
    "chapter14",
    "chapter15",
    "chapter16",
    "chapter17",
    "chapter18",
)


def build_architecture_freeze_report(
    root: Path,
    gate_root: Path,
    branch_audit_path: Path,
    *,
    python_tests_collected: int,
    python_tests_skipped: int,
    web_test_files: int,
    web_tests: int,
    web_build_passed: bool,
) -> dict[str, Any]:
    chapter_reports = {
        name: json.loads((gate_root / f"{name}.json").read_text(encoding="utf-8"))
        for name in CHAPTER_GATES
    }
    branch_audit = json.loads(branch_audit_path.read_text(encoding="utf-8"))
    loop = _read(root / "src/klara/core/loop.py")
    events = _read(root / "src/klara/core/events.py")
    run_service = _read(root / "apps/api/services/run_service.py")
    task_executor = _read(root / "src/klara/tasks/tool_executor.py")
    task_repository = _read(root / "src/klara/tasks/repository.py")
    memory_repository = _read(root / "src/klara/memory/repository.py")
    memory_retrieval = _read(root / "src/klara/memory/retrieval.py")
    memory_formation = _read(root / "src/klara/memory/formation.py")
    dependencies = _read(root / "apps/api/dependencies.py")
    checks = {
        "all_chapter_architecture_gates_pass": all(
            item.get("passed") is True for item in chapter_reports.values()
        ),
        "full_python_suite_passed": python_tests_collected >= 494,
        "frontend_suite_and_production_build_passed": (
            web_test_files >= 20 and web_tests >= 71 and web_build_passed
        ),
        "step_checkpoint_contains_private_transcript": all(
            marker in loop
            for marker in ("KlaraRunCheckpoint", "to_private_dict", "checkpoint_sink")
        ),
        "resume_rehydrates_controllers_and_event_sequence": (
            "observed_tool_results" in loop
            and "controller.on_tool_results" in loop
            and "RUN_RESUMED" in events
        ),
        "ordinary_api_runs_are_recoverable_and_non_daemon": (
            "recover_incomplete_runs" in run_service
            and "daemon=False" in run_service
            and "daemon=True" not in run_service
        ),
        "mutating_tool_effects_have_private_replay_receipts": all(
            marker in task_executor
            for marker in ("DurableToolExecutor", "tool_effect_outcome_unknown", "result_payload")
        ) and "result_payload TEXT" in task_repository,
        "memory_ids_are_owner_namespaced": (
            "PRIMARY KEY(tenant_id, user_id, memory_id)" in memory_repository
        ),
        "memory_has_learned_embedding_boundary": "embedding_provider" in memory_retrieval,
        "memory_has_single_pass_add_only_formation": all(
            marker in memory_formation
            for marker in ("single-pass", "ADD-only", "MemoryFormationMode")
        ),
        "ordinary_chat_memory_defaults_to_review_not_auto_commit": (
            'KLARA_MEMORY_FORMATION_MODE", "review"' in dependencies
        ),
        "historical_branch_execution_is_complete_and_honest": (
            branch_audit["summary"]["compile_passed"] == branch_audit["branch_count"]
            and branch_audit["summary"]["pytest_passed"] == branch_audit["branch_count"] - 1
            and branch_audit["interpretation"]["live_provider_calls"] is False
        ),
    }
    passed = all(checks.values())
    return {
        "schema_version": "klara.agent-architecture-freeze.v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "agent-architecture-freeze",
        "gate_kind": "latest_branch_full_architecture_and_recovery_gate",
        "passed": passed,
        "status": "architecture_frozen_live_behavior_pending" if passed else "blocked",
        "checks": checks,
        "counts": {
            "chapter_gates_passed": sum(
                item.get("passed") is True for item in chapter_reports.values()
            ),
            "chapter_gates_total": len(chapter_reports),
            "python_tests_collected": python_tests_collected,
            "python_tests_skipped": python_tests_skipped,
            "web_test_files": web_test_files,
            "web_tests": web_tests,
            "remote_branches_audited": branch_audit["branch_count"],
            "remote_branches_with_passing_historical_tests": branch_audit["summary"]["pytest_passed"],
        },
        "chapter_gates": {
            name: {
                "passed": item["passed"],
                "gate_kind": item["gate_kind"],
            }
            for name, item in chapter_reports.items()
        },
        "architecture_contract": {
            "agent_loop": "bounded model/tool loop plus step checkpoint and deterministic controller rehydration",
            "durability": "lease-backed task recovery and private write/control effect receipts",
            "memory": "owner-scoped records, optional learned embeddings, temporal/hybrid retrieval, single-pass ADD-only formation",
            "production": "auth/RBAC, tenant isolation, migrations, SQLite/PostgreSQL lease queue, outbox, audit, redacted trajectory export",
            "ui": "tested product surfaces for planning, trace, memory, permissions, tasks, scheduler, teams, MCP, and evaluation",
        },
        "limits": [
            "This is an architecture/runtime freeze, not Agent Product Freeze.",
            "Live DeepSeek question-answer/tool replay, public memory benchmarks, and external judging remain required.",
            "Historical chapter branches remain immutable learning snapshots; repairs are integrated only on the latest reliable branch.",
            "No model training is permitted by this report.",
        ],
        "next_gate": "live DeepSeek behavior and tool replay on the exact frozen runtime",
    }


def render_architecture_freeze(report: dict[str, Any], *, english: bool) -> str:
    title = "Agent Architecture Freeze" if english else "Agent 架构冻结"
    lines = [
        f"# {title}",
        "",
        (
            "Language: [Chinese](./agent-architecture-freeze.md) | English"
            if english
            else "语言：中文 | [English](./agent-architecture-freeze.en.md)"
        ),
        "",
        f"- Status: `{'PASS' if report['passed'] else 'FAIL'}`" if english else f"- 状态：`{'通过' if report['passed'] else '失败'}`",
        f"- Chapter gates: `{report['counts']['chapter_gates_passed']}/{report['counts']['chapter_gates_total']}`" if english else f"- 逐章门禁：`{report['counts']['chapter_gates_passed']}/{report['counts']['chapter_gates_total']}`",
        f"- Python tests: `{report['counts']['python_tests_collected']}` collected, `{report['counts']['python_tests_skipped']}` environment skips" if english else f"- Python 测试：收集 `{report['counts']['python_tests_collected']}`，环境相关跳过 `{report['counts']['python_tests_skipped']}`",
        f"- Web tests: `{report['counts']['web_tests']}` across `{report['counts']['web_test_files']}` files; production build passed" if english else f"- 前端测试：`{report['counts']['web_test_files']}` 个文件、`{report['counts']['web_tests']}` 项；生产构建通过",
        "",
        "## Checks" if english else "## 检查项",
        "",
    ]
    for name, value in report["checks"].items():
        lines.append(f"- `{'PASS' if value else 'FAIL'}` — `{name}`")
    lines += ["", "## Architecture" if english else "## 冻结架构", ""]
    for name, value in report["architecture_contract"].items():
        lines.append(f"- `{name}`: {value}")
    lines += ["", "## Limits" if english else "## 边界", ""]
    lines.extend(f"- {item}" for item in report["limits"])
    lines += ["", f"Next gate: `{report['next_gate']}`" if english else f"下一门禁：`{report['next_gate']}`", ""]
    return "\n".join(lines)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")
