"""Tests for safe evaluation summary projection."""

from __future__ import annotations

import json
from pathlib import Path

from klara.eval.catalog import load_evaluation_summary


def test_summary_omits_case_scores_and_human_review_keys(tmp_path: Path) -> None:
    report = {
        "passed": True,
        "gate_kind": "contract_control_probe",
        "interpretation": "control only",
        "scorer_version": "v1",
        "evaluated_at": "2026-08-13T00:00:00Z",
        "counts": {"cases": 2},
        "metrics": {"normal_task_success_rate": 1.0},
        "checks": {"gate": True},
        "split_hashes": {"hidden_regression": "secret-hash"},
        "case_scores": [{"case_id": "hidden-case"}],
        "human_review_queue": {"items": [{"candidate_slot": "a"}]},
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    summary = load_evaluation_summary(path)

    assert summary["available"]
    assert "case_scores" not in summary
    assert "human_review_queue" not in summary


def test_summary_reports_not_run_when_artifact_is_absent(tmp_path: Path) -> None:
    summary = load_evaluation_summary(tmp_path / "missing.json")

    assert not summary["available"]
    assert summary["status"] == "not_run"
