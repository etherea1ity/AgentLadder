from pathlib import Path

from klara.eval.chapter17 import evaluate_chapter17, render_chapter17_markdown


def test_chapter17_gate_passes_repository_contract() -> None:
    report = evaluate_chapter17(Path.cwd())
    assert report["passed"] is True
    assert report["metrics"]["critical_mcp_rate"] == 1.0
    assert report["metrics"]["public_secret_leak_count"] == 0


def test_chapter17_markdown_mirrors_status_and_checks() -> None:
    report = evaluate_chapter17(Path.cwd())
    chinese = render_chapter17_markdown(report)
    english = render_chapter17_markdown(report, language="en")
    assert "Status: **PASS**" in chinese
    assert "Status: **PASS**" in english
    assert chinese.count("| PASS |") == english.count("| PASS |")
