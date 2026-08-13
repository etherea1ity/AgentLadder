from __future__ import annotations

from pathlib import Path

from klara.eval.chapter12_13 import evaluate_chapter12_13, render_markdown


ROOT = Path(__file__).resolve().parents[3]


def test_chapter12_13_gate_passes_real_loop_and_gold_metrics() -> None:
    report = evaluate_chapter12_13(ROOT)

    assert report["passed"] is True
    assert all(report["checks"].values())
    assert report["metrics"]["citation_precision"] == 1.0
    assert report["metrics"]["citation_recall"] == 1.0
    assert report["metrics"]["contradiction_recall"] == 1.0
    assert report["metrics"]["abstention_accuracy"] == 1.0


def test_chapter12_13_reports_are_structurally_mirrored() -> None:
    report = evaluate_chapter12_13(ROOT)
    zh = render_markdown(report)
    en = render_markdown(report, language="en")

    assert zh.count("\n## ") == en.count("\n## ")
    assert "ch12-13-evidence-runtime.en.md" in zh
    assert "ch12-13-evidence-runtime.md" in en
