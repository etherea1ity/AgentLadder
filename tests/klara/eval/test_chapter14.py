from pathlib import Path

from klara.eval.chapter14 import evaluate_chapter14, render_chapter14_markdown


def test_chapter14_gate_passes_repository_contract() -> None:
    report = evaluate_chapter14(Path.cwd())
    assert report["passed"] is True
    assert report["metrics"]["critical_recovery_isolation_idempotency_rate"] == 1.0
    assert report["metrics"]["public_secret_leak_count"] == 0


def test_chapter14_markdown_mirrors_status_and_checks() -> None:
    report = evaluate_chapter14(Path.cwd())
    chinese = render_chapter14_markdown(report)
    english = render_chapter14_markdown(report, language="en")
    assert "Status: **PASS**" in chinese
    assert "Status: **PASS**" in english
    assert chinese.count("| PASS |") == english.count("| PASS |")
