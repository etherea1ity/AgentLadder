"""Tests for safe evaluation summary projection."""

from __future__ import annotations

import json
from pathlib import Path

from klara.eval.catalog import load_evaluation_catalog, load_evaluation_summary


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


def test_catalog_projects_aggregate_history_without_hidden_rows(tmp_path: Path) -> None:
    (tmp_path / "good.json").write_text(
        json.dumps(
            {
                "passed": False,
                "gate_kind": "behavior_gate",
                "stage": "chapter-x",
                "interpretation": "A safe summary.",
                "scorer_version": "v2",
                "evaluated_at": "2026-08-14T00:00:00Z",
                "counts": {"cases": 5, "ratio": 0.5},
                "metrics": {"task_success": 0.8, "label": "private"},
                "checks": {"quality": False, "numeric": 1},
                "case_scores": [{"case_id": "hidden-case", "prompt": "secret"}],
                "human_review_queue": {"reviewer": "private"},
                "split_hashes": {"hidden": "private-hash"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "ui-only.json").write_text(json.dumps({"passed": True}), encoding="utf-8")

    catalog = load_evaluation_catalog(tmp_path)

    assert catalog["schema_version"] == "klara.evaluation-catalog.v1"
    assert len(catalog["runs"]) == 1
    run = catalog["runs"][0]
    assert run["artifact_id"] == "good"
    assert run["status"] == "failed"
    assert run["counts"] == {"cases": 5}
    assert run["metrics"] == {"task_success": 0.8}
    assert run["checks"] == {"quality": False}
    assert "case_scores" not in run
    assert "split_hashes" not in run
