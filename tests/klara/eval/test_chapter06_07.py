from __future__ import annotations

from pathlib import Path

from klara.eval.chapter06_07 import (
    evaluate_chapter06_07,
    render_chapter06_07_markdown,
)


ROOT = Path(__file__).parents[3]


def test_chapter06_07_gate_exercises_real_product_path() -> None:
    report = evaluate_chapter06_07(ROOT)

    assert report["passed"] is True
    assert report["metrics"]["checks_passed"] == report["metrics"]["checks_total"]
    assert report["metrics"]["model_messages_after_compaction"] < 11
    assert report["metrics"]["messages_summarized"] > 0
    assert report["metrics"]["precompact_projected_events"] == 2


def test_chapter06_07_report_mirrors_heading_structure() -> None:
    report = evaluate_chapter06_07(ROOT)
    chinese = render_chapter06_07_markdown(report)
    english = render_chapter06_07_markdown(report, language="en")

    assert chinese.count("\n## ") == english.count("\n## ")
    assert "ch06-07-context.en.md" in chinese
    assert "ch06-07-context.md" in english
