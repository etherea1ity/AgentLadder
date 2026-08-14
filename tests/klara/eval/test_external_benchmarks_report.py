from __future__ import annotations

from klara.eval.external_benchmarks_report import render_external_benchmark_markdown


def test_external_report_keeps_stage_pass_separate_from_product_freeze() -> None:
    report = {
        "status": "stage_passed_product_freeze_blocked",
        "stage_passed": True,
        "agent_product_freeze_allowed": False,
        "model_training_allowed": False,
        "metrics": {"tau2_official_success_rate": 0.8},
        "blockers": [{"id": "qwen", "detail": "HTTP 401"}],
        "limitations": ["no parity claim"],
    }
    text = render_external_benchmark_markdown(report, language="en")
    assert "Stage gate: `PASS`" in text
    assert "Agent Product Freeze: `BLOCKED`" in text
    assert "Model training: `BLOCKED`" in text
