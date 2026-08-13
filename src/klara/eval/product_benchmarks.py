"""Aggregate local product benchmark evidence without converting pending gates to PASS."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "klara.agent-product-benchmarks.v1"
SCORER_VERSION = "klara.product-benchmarks.v1"


def build_product_benchmark_report(
    *,
    manifest_path: Path,
    runtime_calibration_path: Path,
    locomo_path: Path,
    longmemeval_path: Path,
    memory_agent_bench_path: Path,
    public_agent_path: Path,
    memory_competitors_path: Path,
) -> dict[str, Any]:
    """Combine independently generated reports and keep external gaps explicit."""

    manifest = _read(manifest_path)
    runtime = _read(runtime_calibration_path)
    locomo = _read(locomo_path)
    longmemeval = _read(longmemeval_path)
    memory_agent_bench = _read(memory_agent_bench_path)
    public_agent = _read(public_agent_path)
    competitors = _read(memory_competitors_path)
    local_checks = {
        "runtime_reference_calibration_41_of_41": runtime.get("passed") is True
        and runtime.get("counts", {}).get("observations") == 41,
        "locomo_gold_evidence_retrieval": locomo.get("passed") is True,
        "longmemeval_oracle_contract": longmemeval.get("passed") is True,
        "memory_agent_bench_all_split_contracts": memory_agent_bench.get("passed") is True,
        "agentbench_and_tau2_source_contracts": public_agent.get("passed") is True,
        "mem0_mem1_beam_source_contracts": competitors.get("passed") is True,
        "external_label_merger_is_frozen": "klara.behavior-label-merger.v1"
        in manifest.get("evaluator_versions", []),
        "paid_api_budget_is_zero": float(manifest["budgets"]["paid_api_usd"]) == 0,
        "no_training_before_product_freeze": True,
    }
    mandatory_product_checks = {
        "live_candidate_full_coverage": False,
        "reference_non_inferiority": False,
        "independent_model_judge_full_coverage": False,
        "blind_human_acceptability_at_least_0_95": False,
        "official_agentbench_score": False,
        "official_tau2_score": False,
        "official_mem0_same_model_score": False,
        "official_mem1_gpu_score": False,
        "official_beam_score": False,
    }
    blockers = [
        {
            "id": "paid-api-budget",
            "kind": "external_authority",
            "detail": (
                "The frozen paid API budget is USD 0, so the 41-observation live "
                "candidate and independent judge runs are prohibited."
            ),
            "needed": (
                "Approve a nonzero USD cap and frozen per-million input/output prices "
                "for the candidate and independent judge."
            ),
        },
        {
            "id": "blind-human-review",
            "kind": "external_label",
            "detail": (
                "Blind acceptability cannot be inferred by the same system that "
                "generated or scored the candidate outputs."
            ),
            "needed": "Collect blind labels after candidate outputs exist; target acceptance is at least 95%.",
        },
        {
            "id": "official-public-agent-scores",
            "kind": "external_execution",
            "detail": "AgentBench and tau2 source/task contracts pass, but official environments were not scored.",
            "needed": "Run the pinned official graders with frozen agent/user models and declared budget.",
        },
        {
            "id": "official-memory-competitor-scores",
            "kind": "external_execution",
            "detail": "Mem0, MEM1, and BEAM are pinned but their official comparable pipelines were not executed.",
            "needed": "Use identical data, answer/judge models, top-k, generation limits, and inference budgets; MEM1 additionally requires GPU rollout.",
        },
    ]
    local_passed = all(local_checks.values())
    passed = local_passed and all(mandatory_product_checks.values())
    hybrid = locomo.get("systems", {}).get("hybrid", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "agent-product-benchmarks",
        "status": "passed" if passed else "external_gates_pending",
        "interpretation": (
            "Local deterministic/product-source readiness passes. The Agent Product "
            "Benchmark gate remains failed until live candidate, independent judge, "
            "blind human, and official comparable benchmark scores pass."
        ),
        "manifest": {
            "path": manifest_path.as_posix(),
            "sha256": _sha256(manifest_path),
            "parent_commit": manifest["parent_commit"],
            "branch": manifest["branch"],
            "paid_api_budget_usd": manifest["budgets"]["paid_api_usd"],
            "split_hashes": manifest["split_hashes"],
        },
        "local_checks": local_checks,
        "mandatory_product_checks": mandatory_product_checks,
        "metrics": {
            "klara_bench_cases": runtime["counts"]["cases"],
            "klara_bench_observations": runtime["counts"]["observations"],
            "klara_bench_critical_observations": runtime["counts"]["critical_observations"],
            "locomo_questions": locomo["selection"]["selected_questions"],
            "locomo_hybrid_evidence_recall_at_5": hybrid.get("evidence_recall_at_k"),
            "locomo_hybrid_evidence_hit_at_5": hybrid.get("evidence_hit_at_k"),
            "locomo_hybrid_mrr": hybrid.get("mean_reciprocal_rank"),
            "longmemeval_oracle_questions": longmemeval["selection"]["sample_size"],
            "memory_agent_bench_rows": sum(
                split["rows"] for split in memory_agent_bench["splits"].values()
            ),
            "memory_agent_bench_questions": sum(
                split["questions"] for split in memory_agent_bench["splits"].values()
            ),
            "paid_live_candidate_observations": 0,
            "independent_judge_labels": 0,
            "blind_human_labels": 0,
            "official_public_agent_scores": 0,
            "official_memory_competitor_scores": 0,
        },
        "artifacts": {
            "runtime_calibration": _artifact(runtime_calibration_path),
            "locomo": _artifact(locomo_path),
            "longmemeval": _artifact(longmemeval_path),
            "memory_agent_bench": _artifact(memory_agent_bench_path),
            "public_agent_contracts": _artifact(public_agent_path),
            "memory_competitor_contracts": _artifact(memory_competitors_path),
        },
        "blockers": blockers,
        "local_pre_freeze_ready": local_passed,
        "agent_product_freeze_allowed": passed,
        "model_training_allowed": passed,
        "passed": passed,
    }


def build_human_review_status() -> dict[str, Any]:
    """Describe why no blind queue can exist before paid candidate collection."""

    return {
        "schema_version": "klara.behavior-human-review-status.v1",
        "status": "not_generated",
        "candidate_observations": 0,
        "blind_review_pairs": 0,
        "candidate_slot_exposed": False,
        "reason": "live_candidate_not_executed_under_zero_paid_api_budget",
        "next_step": "Generate the blind queue and private decode key separately after a fully covered candidate run.",
    }


def render_product_benchmark_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    """Render Chinese-first and English-mirror status reports from one result."""

    english = language == "en"
    title = "Agent Product Benchmark Gate" if english else "Agent 产品评测门禁"
    toggle = (
        "Language: [Chinese](./agent-product-benchmarks.md) | English"
        if english
        else "语言：中文 | [English](./agent-product-benchmarks.en.md)"
    )
    status = "PASS" if report["passed"] else "FAIL"
    local_title = "Local verified checks" if english else "本地已验证检查"
    pending_title = "Mandatory pending checks" if english else "强制未完成检查"
    metrics_title = "Measured results" if english else "实测结果"
    blockers_title = "External blockers" if english else "外部阻塞"
    boundary_title = "Interpretation boundary" if english else "解释边界"
    lines = [
        f"# {title}",
        "",
        toggle,
        "",
        f"Status: **{status}**",
        "",
        (
            "The local deterministic and source-contract work passes, but Agent Product Freeze is not allowed."
            if english
            else "本地确定性与来源契约工作已通过，但仍不允许进入 Agent Product Freeze。"
        ),
        "",
        f"## {local_title}",
        "",
        "| Check | Result |" if english else "| 检查 | 结果 |",
        "| --- | --- |",
    ]
    for name, value in report["local_checks"].items():
        lines.append(f"| `{name}` | {'PASS' if value else 'FAIL'} |")
    lines.extend(
        [
            "",
            f"## {pending_title}",
            "",
            "| Check | Result |" if english else "| 检查 | 结果 |",
            "| --- | --- |",
        ]
    )
    for name, value in report["mandatory_product_checks"].items():
        lines.append(f"| `{name}` | {'PASS' if value else 'FAIL'} |")
    lines.extend(
        [
            "",
            f"## {metrics_title}",
            "",
            "| Metric | Value |" if english else "| 指标 | 数值 |",
            "| --- | ---: |",
        ]
    )
    for name, value in report["metrics"].items():
        lines.append(f"| `{name}` | {value} |")
    lines.extend(["", f"## {blockers_title}", ""])
    for blocker in report["blockers"]:
        lines.append(f"- `{blocker['id']}`: {blocker['detail']} {blocker['needed']}")
    boundary = (
        "The 41/41 scripted reference calibration validates wiring, not current-model quality. "
        "LoCoMo is retrieval-only; LongMemEval and MemoryAgentBench runs validate dataset contracts, "
        "not answer accuracy. No general ChatGPT parity or competitor superiority is claimed."
        if english
        else "41/41 脚本参考校准验证的是运行链路，不是当前模型质量；LoCoMo 只测检索，"
        "LongMemEval 与 MemoryAgentBench 当前只验证数据契约，不测答案准确率。"
        "本报告不声称普遍达到 ChatGPT，也不声称优于竞品。"
    )
    lines.extend(["", f"## {boundary_title}", "", boundary, ""])
    return "\n".join(lines)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"report_not_object:{path}")
    return value


def _artifact(path: Path) -> dict[str, Any]:
    return {"path": path.as_posix(), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
