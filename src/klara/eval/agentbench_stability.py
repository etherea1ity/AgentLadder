"""Aggregate immutable AgentBench repeat reports into one stability artifact."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any


SCHEMA_VERSION = "klara.agentbench-stability.v1"


def summarize_agentbench_stability(paths: list[Path]) -> dict[str, Any]:
    if len(paths) < 3:
        raise ValueError("ordinary stochastic stability requires at least 3 runs")
    runs: list[dict[str, Any]] = []
    models: set[str] = set()
    indexes: set[tuple[int, ...]] = set()
    for path in paths:
        raw = path.read_bytes()
        report = json.loads(raw)
        models.add(str(report["candidate"]["model"]))
        indexes.add(tuple(int(case["index"]) for case in report["cases"]))
        runs.append(
            {
                "path": _portable_path(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "passed": bool(report["passed"]),
                "official_rewards": [case["reward"] for case in report["cases"]],
                "semantic_preflight_rejections": int(
                    report["metrics"]["semantic_preflight_rejections"]
                ),
                "model_decision_attempts": float(
                    report["metrics"]["average_model_decision_attempts"]
                ),
                "total_tokens": float(report["metrics"]["average_total_tokens"]),
                "estimated_cost_usd": float(
                    report["metrics"]["estimated_cost_usd"]
                ),
            }
        )
    checks = {
        "minimum_three_repetitions": len(runs) >= 3,
        "same_candidate_model": len(models) == 1,
        "same_declared_indexes": len(indexes) == 1,
        "all_repetitions_passed": all(run["passed"] for run in runs),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "candidate_model": next(iter(models)) if len(models) == 1 else sorted(models),
        "indexes": list(next(iter(indexes))) if len(indexes) == 1 else [],
        "metrics": {
            "repetitions": len(runs),
            "pass_rate": sum(run["passed"] for run in runs) / len(runs),
            "total_semantic_preflight_rejections": sum(
                run["semantic_preflight_rejections"] for run in runs
            ),
            "average_model_decision_attempts": mean(
                run["model_decision_attempts"] for run in runs
            ),
            "average_total_tokens": mean(run["total_tokens"] for run in runs),
            "estimated_cost_usd": round(
                sum(run["estimated_cost_usd"] for run in runs), 8
            ),
        },
        "runs": runs,
        "checks": checks,
        "passed": all(checks.values()),
        "limitations": [
            "This stability result covers only the declared counting sample and is not a full AgentBench score.",
            "Semantic preflight is a general count-intent invariant; it contains no benchmark fixture values or expected answers.",
        ],
    }


def render_stability_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    zh = language == "zh"
    metrics = report["metrics"]
    lines = [
        f"# {'AgentBench 计数决策稳定性' if zh else 'AgentBench Counting Decision Stability'}",
        "",
        (
            "语言：中文 | [English](./agent-product-agentbench-db-live-count-stability.en.md)"
            if zh
            else "Language: [Chinese](./agent-product-agentbench-db-live-count-stability.md) | English"
        ),
        "",
        f"- {'结论' if zh else 'Verdict'}: `{'通过' if report['passed'] and zh else 'PASS' if report['passed'] else '未通过' if zh else 'FAIL'}`",
        f"- {'重复次数' if zh else 'Repetitions'}: `{metrics['repetitions']}`",
        f"- {'成功率' if zh else 'Pass rate'}: `{metrics['pass_rate']}`",
        f"- {'语义预检总拦截数' if zh else 'Total semantic preflight rejections'}: `{metrics['total_semantic_preflight_rejections']}`",
        f"- {'平均模型决策尝试' if zh else 'Average model decision attempts'}: `{metrics['average_model_decision_attempts']}`",
        f"- {'估算总成本' if zh else 'Estimated total cost'}: `${metrics['estimated_cost_usd']}`",
        "",
        f"## {'逐次结果' if zh else 'Per-run Results'}",
        "",
        f"| Run | {'通过' if zh else 'Passed'} | Reward | {'拦截' if zh else 'Rejections'} | {'尝试' if zh else 'Attempts'} |",
        "| ---: | --- | ---: | ---: | ---: |",
    ]
    for number, run in enumerate(report["runs"], start=1):
        lines.append(
            f"| {number} | {run['passed']} | {run['official_rewards']} | "
            f"{run['semantic_preflight_rejections']} | {run['model_decision_attempts']} |"
        )
    lines.extend(["", f"## {'边界' if zh else 'Boundary'}", ""])
    if zh:
        lines.extend(
            [
                "- 只验证预先声明的计数决策样本，不代表完整 AgentBench 分数。",
                "- 语义预检只检查计数意图与 SQL 聚合是否一致，不包含样本名、数据库值或标准答案。",
            ]
        )
    else:
        lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _portable_path(path: Path) -> str:
    parts = path.parts
    if "docs" in parts:
        return Path(*parts[parts.index("docs") :]).as_posix()
    return path.name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument(
        "--output-stem", default="agent-product-agentbench-db-live-count-stability"
    )
    args = parser.parse_args()
    root = args.root.resolve()
    paths = [path if path.is_absolute() else root / path for path in args.input]
    report = summarize_agentbench_stability(paths)
    output = root / "docs" / "reports" / "product"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{args.output_stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / f"{args.output_stem}.md").write_text(
        render_stability_markdown(report), encoding="utf-8"
    )
    (output / f"{args.output_stem}.en.md").write_text(
        render_stability_markdown(report, language="en"), encoding="utf-8"
    )
    print(json.dumps({"passed": report["passed"], "metrics": report["metrics"]}))


if __name__ == "__main__":
    main()
