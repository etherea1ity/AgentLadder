from __future__ import annotations

from pathlib import Path

from klara.eval.chapter05 import evaluate_chapter05, render_chapter05_markdown


ROOT = Path(__file__).parents[3]


def test_chapter05_gate_exercises_real_product_path() -> None:
    report = evaluate_chapter05(ROOT)

    assert report["passed"] is True
    assert report["metrics"]["checks_passed"] == report["metrics"]["checks_total"]
    assert report["metrics"]["sse_plan_events"] == 1
    assert report["metrics"]["trace_plan_events"] == 1
    assert report["probe_plan"]["items"][1]["status"] == "in_progress"


def test_chapter05_report_mirrors_heading_structure() -> None:
    report = evaluate_chapter05(ROOT)
    chinese = render_chapter05_markdown(report)
    english = render_chapter05_markdown(report, language="en")

    assert chinese.count("\n## ") == english.count("\n## ")
    assert "ch05-todo-planning.en.md" in chinese
    assert "ch05-todo-planning.md" in english
