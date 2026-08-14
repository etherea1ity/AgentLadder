from __future__ import annotations

import json
from pathlib import Path

import pytest

from klara.eval.agentbench_stability import (
    render_stability_markdown,
    summarize_agentbench_stability,
)


def _write_run(path: Path, *, passed: bool = True, rejections: int = 1) -> None:
    path.write_text(
        json.dumps(
            {
                "candidate": {"model": "deepseek/deepseek-v4-flash"},
                "passed": passed,
                "cases": [{"index": 20, "reward": 1 if passed else 0}],
                "metrics": {
                    "semantic_preflight_rejections": rejections,
                    "average_model_decision_attempts": 2,
                    "average_total_tokens": 100,
                    "estimated_cost_usd": 0.001,
                },
            }
        ),
        encoding="utf-8",
    )


def test_stability_requires_three_runs(tmp_path: Path) -> None:
    paths = [tmp_path / f"run-{index}.json" for index in range(2)]
    for path in paths:
        _write_run(path)
    with pytest.raises(ValueError, match="at least 3"):
        summarize_agentbench_stability(paths)


def test_stability_aggregates_immutable_run_hashes(tmp_path: Path) -> None:
    paths = [tmp_path / f"run-{index}.json" for index in range(3)]
    for path in paths:
        _write_run(path)
    report = summarize_agentbench_stability(paths)
    assert report["passed"] is True
    assert report["metrics"]["pass_rate"] == 1.0
    assert report["metrics"]["total_semantic_preflight_rejections"] == 3
    assert all(len(run["sha256"]) == 64 for run in report["runs"])
    assert "不代表完整 AgentBench" in render_stability_markdown(report)
