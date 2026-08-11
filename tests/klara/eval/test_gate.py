from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from klara.eval.cli import main, run_gate


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "algorithm"
FIXTURE = FIXTURE_DIR / "gate1_gold.json"
CONFIG = ROOT / "config" / "experiments" / "lab_a_evidence_eval.toml"


def test_gate_passes_every_required_metric() -> None:
    report = run_gate(FIXTURE, CONFIG)

    assert report.passed is True
    assert all(report.checks.values())
    assert report.metrics["citation_precision"] == 1.0
    assert report.metrics["citation_recall"] == 1.0
    assert report.metrics["claim_support_accuracy"] == 1.0
    assert report.metrics["contradiction_recall"] == 1.0
    assert report.metrics["abstention_accuracy"] == 1.0
    assert report.metrics["tool_decision_accuracy"] == 1.0
    assert report.metrics["evidence_selection_recall"] == 1.0


def test_bad_prediction_reduces_score_and_fails_gate(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    changed = deepcopy(fixture)
    changed["cases"][0]["answer"]["links"][0]["judgment"] = "insufficient"
    changed_path = tmp_path / "bad.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")
    (tmp_path / "gate1_trajectories.jsonl").write_bytes(
        (FIXTURE_DIR / "gate1_trajectories.jsonl").read_bytes()
    )

    report = run_gate(changed_path, CONFIG)

    assert report.passed is False
    assert report.metrics["claim_support_accuracy"] < 1.0
    assert report.metrics["abstention_accuracy"] < 1.0


def test_cli_writes_json_and_markdown_from_same_report(tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    exit_code = main(
        [
            "gate",
            "--fixture",
            str(FIXTURE),
            "--config",
            str(CONFIG),
            "--json-out",
            str(json_path),
            "--markdown-out",
            str(markdown_path),
        ]
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["scorer_version"] in markdown
    assert payload["fixture_sha256"] in markdown
    assert "| citation_precision | 1.000000 |" in markdown


def test_tracked_reports_match_the_gate_renderer() -> None:
    report = run_gate(FIXTURE, CONFIG)

    assert (ROOT / "docs/reports/algorithm/lab-a-evidence-eval.json").read_text(
        encoding="utf-8"
    ) == report.to_json()
    assert (ROOT / "docs/reports/algorithm/lab-a-evidence-eval.md").read_text(
        encoding="utf-8"
    ) == report.to_markdown()
