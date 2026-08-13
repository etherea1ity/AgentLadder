"""Tests for the Chapter 4 machine gate."""

from __future__ import annotations

from pathlib import Path

from klara.eval.chapter04 import evaluate_chapter04, render_chapter04_markdown


ROOT = Path(__file__).parents[3]


def test_chapter04_gate_passes_every_frozen_assembly_check() -> None:
    report = evaluate_chapter04(ROOT)

    assert report["passed"]
    assert all(report["checks"].values())
    assert report["metrics"]["checks_passed"] == report["metrics"]["checks_total"]


def test_chapter04_reports_are_bilingual_structural_mirrors() -> None:
    report = evaluate_chapter04(ROOT)
    chinese = render_chapter04_markdown(report)
    english = render_chapter04_markdown(report, language="en")

    assert "English" in chinese
    assert "Chinese" in english
    assert chinese.count("## ") == english.count("## ")
    assert chinese.count("```") == english.count("```")
