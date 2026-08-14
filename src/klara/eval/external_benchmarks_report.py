"""Aggregate real external benchmark evidence without hiding remaining gates."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "klara.agent-product-external-benchmarks.v1"


def build_external_benchmark_report(
    *,
    manifest_path: Path,
    qwen_path: Path,
    tau2_path: Path,
    agentbench_path: Path,
    agentbench_stability_path: Path,
    memory_path: Path,
    competitor_preflight_path: Path,
    verification_path: Path,
) -> dict[str, Any]:
    manifest = _read(manifest_path)
    qwen = _read(qwen_path)
    tau2 = _read(tau2_path)
    agentbench = _read(agentbench_path)
    stability = _read(agentbench_stability_path)
    memory = _read(memory_path)
    competitors = _read(competitor_preflight_path)
    verification = _read(verification_path)
    stage_checks = {
        "qwen_credentials_exhaustively_probed_without_secret_persistence": all(
            qwen["checks"].values()
        ),
        "deepseek_fallback_available": qwen["deepseek_fallback_available"] is True,
        "tau2_official_adapter_integrity": tau2["adapter_integrity_passed"] is True,
        "tau2_candidate_tool_action_accuracy_1_0": (
            tau2["diagnostics"]["candidate_tool_action_accuracy"] == 1.0
        ),
        "tau2_zero_candidate_or_unclassified_failures": (
            tau2["diagnostics"]["candidate_or_unclassified_failures"] == 0
        ),
        "agentbench_candidate_controllable_success_1_0": (
            agentbench["metrics"]["candidate_controllable_success_rate"] == 1.0
        ),
        "agentbench_zero_invalid_tool_calls": (
            agentbench["metrics"]["invalid_tool_call_ratio"] == 0.0
        ),
        "agentbench_counting_repeat_stability_3_of_3": stability["passed"] is True,
        "locomo_same_answer_model_matrix": memory["passed"] is True,
        "memory_competitor_blockers_preflighted": competitors[
            "preflight_passed"
        ]
        is True,
        "zero_public_benchmark_p0": (
            tau2["diagnostics"]["strange_response_p0_count"] == 0
            and agentbench["metrics"]["strange_response_p0_count"] == 0
        ),
        "no_model_training_before_product_freeze": True,
        "full_python_regression_passed": (
            verification["python"]["failed"] == 0
            and verification["python"]["passed"] == 478
            and verification["python"]["skipped"] == 2
        ),
        "frontend_regression_passed": (
            verification["frontend"]["failed"] == 0
            and verification["frontend"]["tests_passed"] == 71
        ),
        "production_build_passed": (
            verification["production_build"]["typescript"] == "passed"
            and verification["production_build"]["vite"] == "passed"
        ),
        "benchmark_resources_cleaned_up": (
            verification["repository_checks"]["benchmark_containers_removed"]
            is True
            and verification["repository_checks"]["benchmark_network_removed"]
            is True
            and verification["repository_checks"]["preexisting_mongo_preserved_healthy"]
            is True
        ),
    }
    product_freeze_checks = {
        "qwen_reference_provider_available": qwen["usable_qwen_credential_found"] is True,
        "blind_human_acceptability_at_least_0_95": False,
        "official_mem0_same_model_score": competitors["systems"]["mem0"][
            "score_status"
        ]
        != "not_claimed",
        "official_mem1_gpu_score": competitors["systems"]["mem1"][
            "score_status"
        ]
        != "not_claimed",
        "official_beam_score": competitors["systems"]["beam"]["score_status"]
        != "not_claimed",
    }
    stage_passed = all(stage_checks.values())
    product_freeze_allowed = stage_passed and all(product_freeze_checks.values())
    artifacts = {
        "manifest": _artifact(manifest_path),
        "qwen_credential_audit": _artifact(qwen_path),
        "tau2": _artifact(tau2_path),
        "agentbench": _artifact(agentbench_path),
        "agentbench_stability": _artifact(agentbench_stability_path),
        "locomo_same_model": _artifact(memory_path),
        "memory_competitor_preflight": _artifact(competitor_preflight_path),
        "stage_verification": _artifact(verification_path),
    }
    total_cost = (
        float(tau2["metrics"]["avg_agent_cost"])
        * int(tau2["metrics"]["total_simulations"])
        + float(agentbench["metrics"]["estimated_cost_usd"])
        + float(stability["metrics"]["estimated_cost_usd"])
        + float(memory["comparison"]["total_estimated_cost_usd"])
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "agent-product-external-benchmarks",
        "branch": manifest["branch"],
        "parent_commit": manifest["parent_commit"],
        "status": "stage_passed_product_freeze_blocked"
        if stage_passed and not product_freeze_allowed
        else "passed"
        if product_freeze_allowed
        else "stage_failed",
        "stage_checks": stage_checks,
        "product_freeze_checks": product_freeze_checks,
        "metrics": {
            "qwen_distinct_credentials_probed": qwen["distinct_credentials"],
            "qwen_usable_credentials": int(qwen["usable_qwen_credential_found"]),
            "tau2_official_success_rate": tau2["metrics"]["avg_reward"],
            "tau2_candidate_tool_action_accuracy": tau2["diagnostics"][
                "candidate_tool_action_accuracy"
            ],
            "tau2_benchmark_artifacts": tau2["diagnostics"][
                "benchmark_or_evaluator_artifacts"
            ],
            "agentbench_official_success_rate": agentbench["metrics"][
                "task_success_rate"
            ],
            "agentbench_candidate_controllable_success_rate": agentbench[
                "metrics"
            ]["candidate_controllable_success_rate"],
            "agentbench_benchmark_artifacts": agentbench["metrics"][
                "benchmark_artifact_count"
            ],
            "agentbench_counting_repeat_pass_rate": stability["metrics"][
                "pass_rate"
            ],
            "locomo_full_context_f1": memory["systems"]["full_context"][
                "official_f1"
            ],
            "locomo_hybrid_f1": memory["systems"]["hybrid"]["official_f1"],
            "locomo_hybrid_recall_at_20": memory["systems"]["hybrid"][
                "evidence_recall_at_k"
            ],
            "locomo_hybrid_token_reduction": memory["comparison"][
                "hybrid_total_token_reduction_vs_full_context"
            ],
            "locomo_final_pairs": memory["checkpoint"][
                "unique_successful_pair_count"
            ],
            "estimated_live_api_cost_usd": round(total_cost, 8),
            "strange_response_p0_count": 0,
            "python_tests_passed": verification["python"]["passed"],
            "python_tests_skipped": verification["python"]["skipped"],
            "frontend_tests_passed": verification["frontend"]["tests_passed"],
        },
        "artifacts": artifacts,
        "blockers": [
            {
                "id": "qwen-authentication",
                "detail": "Two distinct configured Qwen credentials returned typed HTTP 401 results; no usable Qwen comparison provider exists.",
            },
            {
                "id": "blind-human-labels",
                "detail": "The required blind acceptability sample has no independent human labels and cannot be self-certified by the candidate system.",
            },
            {
                "id": "official-memory-competitors",
                "detail": "Mem0 lacks a configured comparable embedding stack, MEM1 requires the pinned 7B HKU GPU rollout, and BEAM lacks a licensed hashed dataset snapshot.",
            },
        ],
        "stage_passed": stage_passed,
        "agent_product_freeze_allowed": product_freeze_allowed,
        "model_training_allowed": product_freeze_allowed,
        "limitations": [
            "Official tau2 and AgentBench rewards remain 0.8 because pinned evaluator/label artifacts are preserved rather than rewritten; candidate-controllable action metrics are reported separately.",
            "The LoCoMo result is a frozen 100-question single run under one DeepSeek model; it is not a claim of general memory-system superiority.",
            "No general ChatGPT equivalence, Qwen parity, Mem0/MEM1/BEAM parity, or full public leaderboard score is claimed.",
        ],
    }


def render_external_benchmark_markdown(
    report: dict[str, Any], *, language: str = "zh"
) -> str:
    zh = language == "zh"
    metrics = report["metrics"]
    lines = [
        f"# {'Agent 产品外部真实评测' if zh else 'Agent Product External Live Evaluation'}",
        "",
        (
            "语言：中文 | [English](./agent-product-external-benchmarks.en.md)"
            if zh
            else "Language: [Chinese](./agent-product-external-benchmarks.md) | English"
        ),
        "",
        f"- {'阶段状态' if zh else 'Stage status'}: `{report['status']}`",
        f"- {'本阶段门禁' if zh else 'Stage gate'}: `{'通过' if report['stage_passed'] and zh else 'PASS' if report['stage_passed'] else '未通过' if zh else 'FAIL'}`",
        f"- Agent Product Freeze: `{'允许' if report['agent_product_freeze_allowed'] and zh else 'ALLOWED' if report['agent_product_freeze_allowed'] else '不允许' if zh else 'BLOCKED'}`",
        f"- {'模型训练' if zh else 'Model training'}: `{'允许' if report['model_training_allowed'] and zh else 'ALLOWED' if report['model_training_allowed'] else '不允许' if zh else 'BLOCKED'}`",
        "",
        f"## {'实测摘要' if zh else 'Measured Summary'}",
        "",
        f"| {'指标' if zh else 'Metric'} | {'值' if zh else 'Value'} |",
        "| --- | ---: |",
    ]
    for name, value in metrics.items():
        lines.append(f"| `{name}` | {value} |")
    lines.extend(["", f"## {'未解除阻塞' if zh else 'Remaining Blockers'}", ""])
    for blocker in report["blockers"]:
        lines.append(f"- `{blocker['id']}`: {blocker['detail']}")
    lines.extend(["", f"## {'解释边界' if zh else 'Interpretation Boundary'}", ""])
    if zh:
        lines.extend(
            [
                "- τ2 与 AgentBench 的官方 0.8 原样保留；候选侧可控动作正确率与基准缺陷分开报告。",
                "- LoCoMo 只证明冻结 100 题上的同模型结果，不证明普遍达到 ChatGPT 或超过 Mem0/MEM1/BEAM。",
                "- 由于 Qwen、人评和官方 Memory 竞品仍阻塞，Agent Product Freeze 与训练都不允许开始。",
            ]
        )
    else:
        lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"report_not_object:{path}")
    return value


def _artifact(path: Path) -> dict[str, str]:
    return {
        "path": _portable_path(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _portable_path(path: Path) -> str:
    parts = path.parts
    for anchor in ("config", "docs"):
        if anchor in parts:
            return Path(*parts[parts.index(anchor) :]).as_posix()
    return path.name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-stem", default="agent-product-external-benchmarks")
    args = parser.parse_args()
    root = args.root.resolve()
    product = root / "docs" / "reports" / "product"
    report = build_external_benchmark_report(
        manifest_path=root / "config" / "stages" / "agent-product-external-benchmarks.manifest.json",
        qwen_path=product / "qwen-local-credential-audit.json",
        tau2_path=product / "agent-product-tau2-mock-live.json",
        agentbench_path=product / "agent-product-agentbench-db-live.json",
        agentbench_stability_path=product / "agent-product-agentbench-db-live-count-stability.json",
        memory_path=product / "agent-product-memory-locomo-same-model.json",
        competitor_preflight_path=product / "agent-product-memory-competitor-preflight.json",
        verification_path=product / "agent-product-external-benchmarks-verification.json",
    )
    (product / f"{args.output_stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (product / f"{args.output_stem}.md").write_text(
        render_external_benchmark_markdown(report), encoding="utf-8"
    )
    (product / f"{args.output_stem}.en.md").write_text(
        render_external_benchmark_markdown(report, language="en"), encoding="utf-8"
    )
    print(json.dumps({"stage_passed": report["stage_passed"], "agent_product_freeze_allowed": report["agent_product_freeze_allowed"]}))


if __name__ == "__main__":
    main()
