"""Strict baseline/candidate comparison for frozen Agent behavior reports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


SCORER_VERSION = "klara.production-regression.v1"


def compare_behavior_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    maximum_latency_ratio: float = 1.25,
    maximum_token_ratio: float = 1.10,
    maximum_cost_ratio: float = 1.10,
) -> dict[str, Any]:
    """Reject fixture drift, behavioral regression, P0s, and budget inflation."""

    for label, report in (("baseline", baseline), ("candidate", candidate)):
        if report.get("schema_version") != "klara.behavior-report.v1":
            raise ValueError(f"{label} is not a behavior report")
    if baseline.get("fixture_sha256") != candidate.get("fixture_sha256"):
        raise ValueError("baseline and candidate fixtures differ")
    if baseline.get("split_hashes") != candidate.get("split_hashes"):
        raise ValueError("baseline and candidate split hashes differ")
    if baseline.get("counts", {}).get("observations") != candidate.get("counts", {}).get("observations"):
        raise ValueError("baseline and candidate observation counts differ")
    before = baseline["metrics"]
    after = candidate["metrics"]
    ratios = {
        "latency": _ratio(after["total_latency_ms"], before["total_latency_ms"]),
        "tokens": _ratio(after["total_tokens"], before["total_tokens"]),
        "cost": _ratio(after["total_cost_usd"], before["total_cost_usd"]),
    }
    checks = {
        "candidate_gate_passed": bool(candidate.get("passed")),
        "critical_non_regression": after["critical_deterministic_rate"] >= before["critical_deterministic_rate"],
        "overall_non_regression": after["overall_task_success_rate"] >= before["overall_task_success_rate"],
        "normal_non_regression": after["normal_task_success_rate"] >= before["normal_task_success_rate"],
        "reference_gap_non_regression": after["reference_gap"] <= before["reference_gap"],
        "judge_non_regression": after["judge_equivalent_or_better_rate"] >= before["judge_equivalent_or_better_rate"],
        "human_non_regression": after["human_acceptability_rate"] >= before["human_acceptability_rate"],
        "p0_zero": int(after["p0_count"]) == 0,
        "severe_mismatch_non_regression": after["severe_answer_mismatch_rate"] <= before["severe_answer_mismatch_rate"],
        "latency_budget": ratios["latency"] <= maximum_latency_ratio,
        "token_budget": ratios["tokens"] <= maximum_token_ratio,
        "cost_budget": ratios["cost"] <= maximum_cost_ratio,
    }
    deltas = {
        key: float(after[key]) - float(before[key])
        for key in (
            "critical_deterministic_rate",
            "overall_task_success_rate",
            "normal_task_success_rate",
            "reference_gap",
            "judge_equivalent_or_better_rate",
            "human_acceptability_rate",
            "severe_answer_mismatch_rate",
            "total_latency_ms",
            "total_tokens",
            "total_cost_usd",
        )
    }
    return {
        "schema_version": "klara.production-regression-report.v1",
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "fixture_sha256": candidate["fixture_sha256"],
        "baseline_scorer_version": baseline.get("scorer_version"),
        "candidate_scorer_version": candidate.get("scorer_version"),
        "ratios": ratios,
        "limits": {
            "maximum_latency_ratio": maximum_latency_ratio,
            "maximum_token_ratio": maximum_token_ratio,
            "maximum_cost_ratio": maximum_cost_ratio,
        },
        "deltas": deltas,
        "checks": checks,
        "passed": all(checks.values()),
    }


def render_regression_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    english = language == "en"
    lines = [
        "# Production Agent Regression Gate" if english else "# 生产 Agent 回归门禁",
        "",
        "Language: [Chinese](./ch18-production-runtime-regression.md) | English" if english else "语言：中文 | [English](./ch18-production-runtime-regression.en.md)",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Fixture' if english else '数据集'} SHA-256: `{report['fixture_sha256']}`",
        "",
        "## Acceptance Checks" if english else "## 验收检查",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | {'PASS' if passed else 'FAIL'} |" for name, passed in sorted(report["checks"].items()))
    lines.extend(["", "## Resource Ratios" if english else "## 资源比率", "", "| Metric | Candidate / baseline |", "| --- | ---: |"])
    lines.extend(f"| {name} | {value:.6f} |" for name, value in sorted(report["ratios"].items()))
    lines.extend([
        "",
        "A pass proves non-regression only on the identical frozen fixture, split hashes, scorer, and budgets." if english else "通过仅证明候选在同一份冻结 fixture、split 哈希、评分器与预算下没有回退。",
        "",
    ])
    return "\n".join(lines)


def _ratio(candidate: float | int, baseline: float | int) -> float:
    if float(baseline) == 0:
        return 1.0 if float(candidate) == 0 else float("inf")
    return float(candidate) / float(baseline)
