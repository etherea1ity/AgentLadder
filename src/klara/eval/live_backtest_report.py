"""Aggregate the real Agent product backtest without inventing external labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from klara.eval.behavior import stable_hash


def build_live_backtest_report(root: Path) -> dict[str, Any]:
    reports = root / "docs" / "reports" / "product"
    manifest = _read(root / "config" / "stages" / "agent-product-live-backtest.manifest.json")
    smoke = _read(reports / "agent-product-live-provider-smoke.json")
    reference = _read(reports / "agent-product-live-reference-runtime-calibration.json")
    baseline = _read(reports / "agent-product-live-candidate-deepseek.baseline.json")
    initial = _read(reports / "agent-product-live-candidate-deepseek.post-initial-fix.json")
    pre_contract = _read(
        reports / "agent-product-live-candidate-deepseek.pre-response-contract.json"
    )
    pre_clarification = _read(
        reports / "agent-product-live-candidate-deepseek.pre-clarification-state-fix.json"
    )
    candidate = _read(reports / "agent-product-live-candidate-deepseek.json")
    stage = _read(reports / "agent-product-live-stage-candidate-deepseek.json")
    todo_repair = _read(reports / "agent-product-live-todo-repair-deepseek.json")
    qwen = _read(reports / "agent-product-live-qwen-availability.json")
    fallback = _read(reports / "ch08-provider-live-fallback.json")
    tooling = _read(reports / "agent-product-live-tooling-backtest.json")
    locomo = _read(reports / "memory-public-locomo.json")
    longmemeval = _read(reports / "memory-public-longmemeval.json")
    memory_agent_bench = _read(reports / "memory-public-agent-bench.json")
    memory_competitors = _read(reports / "memory-public-competitor-contracts.json")
    public_agent_contracts = _read(
        reports / "agent-product-benchmarks-public-agent-contracts.json"
    )
    branch_audit = _read(reports / "agent-product-live-branch-audit.json")

    deterministic_checks = {
        "reference_runtime_calibration_41_of_41": reference.get("passed") is True
        and reference.get("counts", {}).get("observations") == 41,
        "deepseek_live_observation_coverage_41_of_41": candidate.get("counts", {}).get(
            "observations"
        )
        == 41,
        "deepseek_live_overall_deterministic_41_of_41": candidate.get("metrics", {}).get(
            "overall_task_success_rate"
        )
        == 1.0,
        "deepseek_live_critical_20_of_20": candidate.get("metrics", {}).get(
            "critical_deterministic_rate"
        )
        == 1.0,
        "deepseek_live_all_repeat_stability": candidate.get("checks", {}).get(
            "critical_repeat_stability"
        )
        is True
        and candidate.get("checks", {}).get("ordinary_repeat_stability") is True,
        "deepseek_live_p0_zero": candidate.get("metrics", {}).get("p0_count") == 0,
        "deepseek_live_provider_errors_zero": not any(
            row.get("provider_error") for row in candidate.get("runtime_runs", [])
        ),
        "todo_repair_live_3_of_3": todo_repair.get("metrics", {}).get(
            "overall_task_success_rate"
        )
        == 1.0,
        "stage_critical_15_of_15": stage.get("metrics", {}).get(
            "critical_deterministic_rate"
        )
        == 1.0,
        "live_qwen_auth_to_deepseek_fallback": fallback.get("passed") is True,
        "live_evidence_mcp_team_tool_decisions_3_of_3": tooling.get("passed") is True
        and tooling.get("metrics", {}).get("cases_passed") == 3
        and tooling.get("metrics", {}).get("strange_response_p0_count") == 0,
        "locomo_retrieval_gate": locomo.get("passed") is True,
        "longmemeval_oracle_contract": longmemeval.get("passed") is True,
        "memory_agent_bench_all_split_contracts": memory_agent_bench.get("passed")
        is True,
        "mem0_mem1_beam_pinned_source_contracts": memory_competitors.get("passed")
        is True,
        "agentbench_tau2_pinned_source_contracts": public_agent_contracts.get("passed")
        is True,
        "all_16_frozen_branches_audited": branch_audit.get("passed") is True
        and branch_audit.get("metrics", {}).get("frozen_branches") == 16
        and branch_audit.get("metrics", {}).get(
            "current_cumulative_capabilities_covered"
        )
        == 16,
    }
    external_checks = {
        "qwen_candidate_available": qwen.get("available") is True,
        "independent_cross_provider_judge_41_of_41": candidate.get("counts", {}).get(
            "judge_scored"
        )
        == 41,
        "blind_human_review_41_of_41": candidate.get("counts", {}).get("human_scored")
        == 41,
        "official_agentbench_comparable_score": False,
        "official_tau2_comparable_score": False,
        "memory_same_model_answer_quality_matrix": False,
        "official_mem0_comparable_score": False,
        "official_mem1_gpu_score": False,
        "official_beam_score": False,
    }
    history = [
        _history_row("initial_live_baseline", baseline),
        _history_row("post_initial_repairs", initial),
        _history_row("pre_response_contract", pre_contract),
        _history_row("pre_clarification_state_fix", pre_clarification),
        _history_row("final_runner_v6", candidate),
    ]
    codex_reference = {
        "kind": "codex_gpt_5_6_authored_public_reference_not_openai_api_run",
        "fixture_source": "repository-authored-by-codex-gpt-5.6",
        "reference_observations": reference.get("counts", {}).get("observations"),
        "reference_runtime_contract_passed": reference.get("passed") is True,
        "candidate_observations": candidate.get("counts", {}).get("observations"),
        "candidate_deterministic_rate": candidate.get("metrics", {}).get(
            "overall_task_success_rate"
        ),
        "comparison_unit": manifest.get("execution_contract", {}).get("comparison_unit"),
        "hidden_reasoning_collected": False,
        "boundary": (
            "The Codex-authored public answers and action paths were replayed through "
            "the real Harness. This is an auditable public-reference comparison, not a "
            "claim that an OpenAI API reference model was called."
        ),
    }
    final_checks = {**deterministic_checks, **external_checks}
    return {
        "schema_version": "klara.agent-product-live-backtest.v1",
        "stage": "agent-product-live-backtest",
        "status": "blocked_external_gates",
        "passed": all(final_checks.values()),
        "agent_product_freeze": False,
        "manifest_sha256": stable_hash(manifest),
        "runner_version": candidate.get("runner_version"),
        "model": candidate.get("model"),
        "checks": final_checks,
        "deterministic_product_gate_passed": all(deterministic_checks.values()),
        "external_gate_passed": all(external_checks.values()),
        "metrics": {
            "main_observations": candidate.get("counts", {}).get("observations"),
            "main_deterministic_rate": candidate.get("metrics", {}).get(
                "overall_task_success_rate"
            ),
            "main_critical_rate": candidate.get("metrics", {}).get(
                "critical_deterministic_rate"
            ),
            "main_p0_count": candidate.get("metrics", {}).get("p0_count"),
            "main_provider_error_count": sum(
                bool(row.get("provider_error")) for row in candidate.get("runtime_runs", [])
            ),
            "main_estimated_cost_usd": candidate.get("estimated_cost_usd"),
            "stage_observations": stage.get("counts", {}).get("observations"),
            "stage_deterministic_rate_before_todo_repair": stage.get("metrics", {}).get(
                "overall_task_success_rate"
            ),
            "todo_repair_rate": todo_repair.get("metrics", {}).get(
                "overall_task_success_rate"
            ),
            "judge_scored": candidate.get("counts", {}).get("judge_scored"),
            "human_scored": candidate.get("counts", {}).get("human_scored"),
            "live_tooling_cases": tooling.get("metrics", {}).get("cases_total"),
            "live_tooling_tokens": tooling.get("metrics", {}).get("total_tokens"),
            "locomo_hybrid_recall_at_5": locomo.get("systems", {})
            .get("hybrid", {})
            .get("evidence_recall_at_k"),
            "locomo_hybrid_hit_at_5": locomo.get("systems", {})
            .get("hybrid", {})
            .get("evidence_hit_at_k"),
            "longmemeval_contract_questions": longmemeval.get("selection", {}).get(
                "sample_size"
            ),
            "memory_agent_bench_rows": sum(
                split.get("rows", 0)
                for split in memory_agent_bench.get("splits", {}).values()
            ),
        },
        "codex_public_reference_comparison": codex_reference,
        "regression_history": history,
        "provider_availability": {
            "deepseek": next(
                row for row in smoke.get("cases", []) if str(row.get("requested_model", "")).startswith("deepseek/")
            ),
            "qwen": qwen,
        },
        "strange_response_audit": {
            "initial_p0_count": baseline.get("metrics", {}).get("p0_count"),
            "final_p0_count": candidate.get("metrics", {}).get("p0_count"),
            "fixed_classes": [
                "provider empty responses no longer abort the batch",
                "untrusted memory is model-visible as untrusted data",
                "exact-field requests no longer leak extra tool metadata",
                "approval answers no longer invite confirmation or retry",
                "destructive home-directory requests receive a bounded scope refusal",
                "latest explicit correction is resolved from transcript context",
                "natural Chinese paraphrases are not misgraded as answer mismatch",
            ],
            "remaining_p0_classes": [],
        },
        "blockers": [
            "Both locally discovered Qwen credential candidates returned HTTP 401, so candidate B and the cross-provider judge could not run.",
            "The 41-item blind human review queue is generated, but no human labels have been supplied; labels were not fabricated.",
            "AgentBench and tau2 source contracts are pinned, but their official comparable graders have not run.",
            "LoCoMo retrieval and the LongMemEval/MemoryAgentBench data contracts pass, but the same-answer-model memory matrix and official Mem0, MEM1, and BEAM scores have not run.",
        ],
        "training_gate": {
            "training_started": False,
            "hku_started": False,
            "reason": (
                "Agent Product Freeze remains false until the independent judge, "
                "blind human review, official public-agent scores, and comparable "
                "memory-system matrix are complete."
            ),
        },
        "artifacts": {
            "candidate": "agent-product-live-candidate-deepseek.json",
            "human_review_queue": "agent-product-live-human-review.json",
            "reference_calibration": "agent-product-live-reference-runtime-calibration.json",
            "provider_smoke": "agent-product-live-provider-smoke.json",
            "qwen_availability": "agent-product-live-qwen-availability.json",
            "todo_repair": "agent-product-live-todo-repair-deepseek.json",
            "live_provider_fallback": "ch08-provider-live-fallback.json",
            "live_tooling": "agent-product-live-tooling-backtest.json",
            "memory_locomo": "memory-public-locomo.json",
            "memory_longmemeval": "memory-public-longmemeval.json",
            "memory_agent_bench": "memory-public-agent-bench.json",
            "memory_competitor_contracts": "memory-public-competitor-contracts.json",
            "branch_audit": "agent-product-live-branch-audit.json",
            "exact_runtime_integration": "agent-runtime-integration.exact-commit-live.json",
        },
    }


def render_live_backtest_markdown(report: dict[str, Any], *, language: str) -> str:
    english = language == "en"
    title = "Agent Product Live Backtest" if english else "Agent 产品真实回测"
    language_line = (
        "Language: [Chinese](./agent-product-live-backtest.md) | English"
        if english
        else "语言：中文 | [English](./agent-product-live-backtest.en.md)"
    )
    lines = [
        f"# {title}",
        "",
        language_line,
        "",
        f"Status: **{report['status']}**",
        "",
        f"- {'Model' if english else '模型'}: `{report['model']}`",
        f"- {'Runner' if english else '运行器'}: `{report['runner_version']}`",
        f"- {'Deterministic product gate' if english else '确定性产品门'}: `{'PASS' if report['deterministic_product_gate_passed'] else 'FAIL'}`",
        f"- {'Agent Product Freeze' if english else 'Agent 产品冻结'}: `FAIL`",
        "",
        "## Metrics" if english else "## 指标",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in report["metrics"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Checks" if english else "## 检查",
            "",
            "| Check | Result |",
            "| --- | --- |",
        ]
    )
    for key, value in report["checks"].items():
        lines.append(f"| {key} | {'PASS' if value else 'FAIL'} |")
    reference = report["codex_public_reference_comparison"]
    lines.extend(
        [
            "",
            "## Codex Public Reference" if english else "## Codex 公开参考对比",
            "",
            reference["boundary"],
            "",
            "## Regression History" if english else "## 回归历史",
            "",
            "| Stage | Success | P0 |",
            "| --- | ---: | ---: |",
        ]
    )
    for row in report["regression_history"]:
        lines.append(
            f"| {row['name']} | {row['overall_task_success_rate']:.6f} | {row['p0_count']} |"
        )
    lines.extend(["", "## Blockers" if english else "## 阻塞项", ""])
    lines.extend(f"- {item}" for item in report["blockers"])
    lines.extend(
        [
            "",
            "## Training Boundary" if english else "## 训练边界",
            "",
            report["training_gate"]["reason"],
            "",
        ]
    )
    return "\n".join(lines)


def _history_row(name: str, report: dict[str, Any]) -> dict[str, Any]:
    metrics = report.get("metrics", {})
    return {
        "name": name,
        "overall_task_success_rate": float(metrics.get("overall_task_success_rate", 0)),
        "critical_deterministic_rate": float(metrics.get("critical_deterministic_rate", 0)),
        "p0_count": int(metrics.get("p0_count", 0)),
    }


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
