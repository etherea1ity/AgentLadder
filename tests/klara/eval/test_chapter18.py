from pathlib import Path

from klara.eval.chapter18 import evaluate_chapter18, render_chapter18_markdown


def test_chapter18_gate_passes() -> None:
    report = evaluate_chapter18(Path.cwd())
    assert report["passed"] is True
    assert report["metrics"]["critical_contract_rate"] == 1.0
    assert report["metrics"]["public_secret_leak_count"] == 0


def test_chapter18_report_is_bilingual() -> None:
    report = evaluate_chapter18(Path.cwd())
    assert "问题—回答一致性探针" in render_chapter18_markdown(report)
    assert "Question/Answer Consistency Probe" in render_chapter18_markdown(report, language="en")
