"""Aggregate behavior scores into one anti-gaming JSON and Markdown report."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from klara.eval.behavior import BehaviorCaseScore, BehaviorFixture, SCORER_VERSION, wilson_interval


def build_behavior_report(
    fixture: BehaviorFixture,
    scores: Iterable[BehaviorCaseScore],
    *,
    thresholds: dict[str, float | int],
    fixture_sha256: str,
) -> dict[str, Any]:
    """Build one report where critical deterministic failures cannot average away."""

    materialized = tuple(scores)
    if not materialized:
        raise ValueError("behavior report requires at least one score")
    success_count = sum(score.task_success for score in materialized)
    critical = tuple(score for score in materialized if score.critical)
    ordinary = tuple(score for score in materialized if not score.critical)
    critical_success = sum(score.task_success for score in critical)
    reference_pairs = tuple(
        score for score in materialized if score.reference_success is not None
    )
    candidate_reference_rate = _rate(
        sum(score.task_success for score in reference_pairs), len(reference_pairs)
    )
    reference_rate = _rate(
        sum(bool(score.reference_success) for score in reference_pairs), len(reference_pairs)
    )
    judge_scores = tuple(
        score for score in materialized if score.judge_outcome != "unscored"
    )
    judge_equivalent = sum(
        score.judge_outcome in {"better", "equivalent"} for score in judge_scores
    )
    human_scores = tuple(
        score for score in materialized if score.human_acceptable is not None
    )
    human_accepted = sum(bool(score.human_acceptable) for score in human_scores)
    expected_observations = sum(case.repetitions for case in fixture.cases)
    expected_keys = {
        (case.case_id, repetition)
        for case in fixture.cases
        for repetition in range(1, case.repetitions + 1)
    }
    observed_keys = [(score.case_id, score.repetition) for score in materialized]
    observation_coverage = (
        len(observed_keys) == len(set(observed_keys))
        and set(observed_keys) == expected_keys
    )
    p0_count = sum(score.p0_count for score in materialized)
    severe_mismatch_rate = _rate(p0_count, len(materialized))
    stability = _stability(materialized)
    metrics = {
        "critical_deterministic_rate": _rate(critical_success, len(critical)),
        "overall_task_success_rate": _rate(success_count, len(materialized)),
        "normal_task_success_rate": _rate(
            sum(score.task_success for score in ordinary), len(ordinary)
        ),
        "reference_success_rate": reference_rate,
        "candidate_reference_success_rate": candidate_reference_rate,
        "reference_gap": max(0.0, reference_rate - candidate_reference_rate),
        "judge_equivalent_or_better_rate": _rate(judge_equivalent, len(judge_scores)),
        "human_acceptability_rate": _rate(human_accepted, len(human_scores)),
        "p0_count": p0_count,
        "severe_answer_mismatch_rate": severe_mismatch_rate,
        "total_latency_ms": sum(score.latency_ms for score in materialized),
        "total_tokens": sum(score.tokens for score in materialized),
        "total_cost_usd": sum(score.cost_usd for score in materialized),
    }
    checks = {
        "observation_coverage": observation_coverage,
        "critical_deterministic": metrics["critical_deterministic_rate"]
        >= float(thresholds["critical_deterministic_rate"]),
        "normal_task_success": metrics["normal_task_success_rate"]
        >= float(thresholds["normal_task_success_rate"]),
        "reference_non_inferiority": bool(reference_pairs)
        and len(reference_pairs) == expected_observations
        and metrics["reference_gap"] <= float(thresholds["maximum_reference_gap"]),
        "independent_judge": bool(judge_scores)
        and len(judge_scores) == expected_observations
        and metrics["judge_equivalent_or_better_rate"]
        >= float(thresholds["judge_equivalent_or_better_rate"]),
        "human_acceptability": bool(human_scores)
        and len(human_scores) == expected_observations
        and metrics["human_acceptability_rate"]
        >= float(thresholds["human_acceptability_rate"]),
        "p0_zero": p0_count <= int(thresholds["maximum_p0_count"]),
        "severe_answer_mismatch": severe_mismatch_rate
        < float(thresholds["maximum_severe_answer_mismatch_rate"]),
        "critical_repeat_stability": all(
            item["passed"] for item in stability if item["critical"]
        ),
        "ordinary_repeat_stability": all(
            item["passed"] for item in stability if not item["critical"]
        ),
    }
    success_interval = wilson_interval(success_count, len(materialized))
    return {
        "schema_version": "klara.behavior-report.v1",
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "fixture_sha256": fixture_sha256,
        "split_hashes": fixture.split_hashes(),
        "counts": {
            "cases": len(fixture.cases),
            "observations": len(materialized),
            "critical_observations": len(critical),
            "judge_scored": len(judge_scores),
            "human_scored": len(human_scores),
            "expected_observations": expected_observations,
        },
        "metrics": metrics,
        "success_rate_95pct_ci": list(success_interval),
        "stability": stability,
        "language_breakdown": _breakdown(materialized, "language"),
        "capability_breakdown": _capability_breakdown(materialized),
        "split_breakdown": _breakdown(materialized, "split"),
        "checks": checks,
        "case_scores": [score.to_dict() for score in materialized],
        "passed": all(checks.values()),
    }


def render_behavior_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    """Render a Chinese report or structurally identical English mirror."""

    english = language == "en"
    title = "Agent Behavior Evaluation" if english else "Agent 行为评测"
    language_line = (
        "Language: [Chinese](./agent-eval-contract.md) | English"
        if english
        else "语言：中文 | [English](./agent-eval-contract.en.md)"
    )
    status = "PASS" if report["passed"] else "FAIL"
    metrics_title = "Metrics" if english else "指标"
    checks_title = "Acceptance Checks" if english else "验收检查"
    limits_title = "Interpretation Boundary" if english else "解释边界"
    metric_label = "Metric" if english else "指标"
    value_label = "Value" if english else "值"
    check_label = "Check" if english else "检查"
    result_label = "Result" if english else "结果"
    interpretation = report.get("interpretation", "")
    if not english and report.get("gate_kind") == "contract_control_probe":
        interpretation = "验证 schema、评分器、阈值、split 隔离、报告渲染和盲评连接；它不衡量当前 Agent 产品能力。"
    lines = [
        f"# {title}",
        "",
        language_line,
        "",
        f"Status: **{status}**",
        "",
        f"- {'Gate kind' if english else '门禁类型'}: `{report.get('gate_kind', 'candidate_evaluation')}`",
        f"- Scorer: `{report['scorer_version']}`",
        f"- Fixture SHA-256: `{report['fixture_sha256']}`",
        f"- Observations: `{report['counts']['observations']}`",
        f"- {'Interpretation' if english else '解释'}: {interpretation}",
        "",
        f"## {metrics_title}",
        "",
        f"| {metric_label} | {value_label} |",
        "| --- | ---: |",
    ]
    for key, value in sorted(report["metrics"].items()):
        lines.append(f"| {key} | {_format(value)} |")
    lines.extend(
        [
            "",
            f"## {checks_title}",
            "",
            f"| {check_label} | {result_label} |",
            "| --- | --- |",
        ]
    )
    for key, value in sorted(report["checks"].items()):
        lines.append(f"| {key} | {'PASS' if value else 'FAIL'} |")
    boundary = (
        "A passing report proves non-inferiority only on the frozen cases, tools, permissions, budgets, reference version, and graders. It is not a claim of general ChatGPT equivalence."
        if english
        else "通过只证明候选在冻结用例、工具、权限、预算、参考版本和评分器上的非劣性；它不代表普遍达到 ChatGPT 能力。"
    )
    lines.extend(["", f"## {limits_title}", "", boundary, ""])
    return "\n".join(lines)


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _stability(scores: tuple[BehaviorCaseScore, ...]) -> list[dict[str, Any]]:
    grouped: dict[str, list[BehaviorCaseScore]] = {}
    for score in scores:
        grouped.setdefault(score.case_id, []).append(score)
    result = []
    for case_id, items in sorted(grouped.items()):
        successes = sum(item.task_success for item in items)
        critical = items[0].critical
        required = 5 if critical else 3
        result.append(
            {
                "case_id": case_id,
                "critical": critical,
                "runs": len(items),
                "successes": successes,
                "required_runs": required,
                "passed": len(items) >= required and successes == len(items),
            }
        )
    return result


def _breakdown(scores: tuple[BehaviorCaseScore, ...], field: str) -> dict[str, Any]:
    grouped: dict[str, list[BehaviorCaseScore]] = {}
    for score in scores:
        grouped.setdefault(str(getattr(score, field)), []).append(score)
    return {
        key: {
            "observations": len(items),
            "success_rate": _rate(sum(item.task_success for item in items), len(items)),
        }
        for key, items in sorted(grouped.items())
    }


def _capability_breakdown(scores: tuple[BehaviorCaseScore, ...]) -> dict[str, Any]:
    grouped: dict[str, list[BehaviorCaseScore]] = {}
    for score in scores:
        for tag in score.capability_tags:
            grouped.setdefault(tag, []).append(score)
    return {
        key: {
            "observations": len(items),
            "success_rate": _rate(sum(item.task_success for item in items), len(items)),
        }
        for key, items in sorted(grouped.items())
    }


def _format(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
