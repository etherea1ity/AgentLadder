from __future__ import annotations

from pathlib import Path

from klara.eval.chapter10 import evaluate_chapter10, render_chapter10_markdown


ROOT = Path(__file__).resolve().parents[3]


def test_chapter10_gate_exercises_real_memory_path() -> None:
    report = evaluate_chapter10(ROOT)

    assert report["passed"] is True
    assert report["metrics"]["tenant_isolation_failure_count"] == 0
    assert report["metrics"]["raw_deleted_content_occurrences"] == 0
    assert report["metrics"]["hybrid_critical_top1_accuracy"] == 1.0


def test_chapter10_report_mirrors_heading_structure() -> None:
    report = evaluate_chapter10(ROOT)
    chinese = render_chapter10_markdown(report)
    english = render_chapter10_markdown(report, language="en")

    assert chinese.count("\n## ") == english.count("\n## ")
    assert "不表示" in chinese
    assert "does not claim" in english
