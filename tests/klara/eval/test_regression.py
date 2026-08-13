from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from klara.eval.regression import compare_behavior_reports, render_regression_markdown


REPORT = Path("docs/reports/product/ch16-subagents-team-worktree-behavior-control.json")


def test_identical_frozen_report_passes_regression() -> None:
    baseline = json.loads(REPORT.read_text(encoding="utf-8"))
    report = compare_behavior_reports(baseline, copy.deepcopy(baseline))
    assert report["passed"] is True
    assert all(value == 0 for value in report["deltas"].values())
    assert "生产 Agent 回归门禁" in render_regression_markdown(report)
    assert "Production Agent Regression Gate" in render_regression_markdown(report, language="en")


def test_behavior_or_budget_regression_fails_and_fixture_drift_rejects() -> None:
    baseline = json.loads(REPORT.read_text(encoding="utf-8"))
    candidate = copy.deepcopy(baseline)
    candidate["metrics"]["overall_task_success_rate"] -= 0.01
    candidate["metrics"]["p0_count"] = 1
    candidate["metrics"]["total_tokens"] *= 2
    report = compare_behavior_reports(baseline, candidate)
    assert report["passed"] is False
    assert report["checks"]["overall_non_regression"] is False
    assert report["checks"]["p0_zero"] is False
    assert report["checks"]["token_budget"] is False

    drift = copy.deepcopy(candidate)
    drift["fixture_sha256"] = "different"
    with pytest.raises(ValueError, match="fixtures differ"):
        compare_behavior_reports(baseline, drift)
