from pathlib import Path

from klara.eval.chapter16 import evaluate_chapter16, render_chapter16_markdown


def test_chapter16_gate_passes() -> None:
    report = evaluate_chapter16(Path.cwd())
    assert report["passed"] is True
    assert report["metrics"]["critical_delegation_isolation_rate"] == 1.0
    assert report["metrics"]["public_secret_leak_count"] == 0


def test_chapter16_report_is_bilingual() -> None:
    report = evaluate_chapter16(Path.cwd())
    assert "问题—回答一致性探针" in render_chapter16_markdown(report)
    assert "Question/Answer Consistency Probe" in render_chapter16_markdown(report, language="en")
