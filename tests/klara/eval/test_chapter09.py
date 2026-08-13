"""Regression tests for the Chapter 9 machine gate."""

from pathlib import Path

from klara.eval.chapter09 import evaluate_chapter09


def test_chapter09_gate_passes_current_repository() -> None:
    report = evaluate_chapter09(Path.cwd())
    assert report["passed"] is True
    assert report["metrics"]["checks_passed"] == report["metrics"]["checks_total"]
