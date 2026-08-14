from __future__ import annotations

from pathlib import Path

from klara.eval.live_backtest_report import (
    build_live_backtest_report,
    render_live_backtest_markdown,
)


ROOT = Path(__file__).parents[3]


def test_live_backtest_keeps_external_gates_red_without_fabrication() -> None:
    report = build_live_backtest_report(ROOT)

    assert report["deterministic_product_gate_passed"] is True
    assert report["metrics"]["main_deterministic_rate"] == 1.0
    assert report["metrics"]["main_critical_rate"] == 1.0
    assert report["checks"]["independent_cross_provider_judge_41_of_41"] is False
    assert report["checks"]["blind_human_review_41_of_41"] is False
    assert report["agent_product_freeze"] is False
    assert report["passed"] is False


def test_live_backtest_markdown_has_bilingual_language_toggles() -> None:
    report = build_live_backtest_report(ROOT)

    chinese = render_live_backtest_markdown(report, language="zh")
    english = render_live_backtest_markdown(report, language="en")

    assert "[English](./agent-product-live-backtest.en.md)" in chinese
    assert "[Chinese](./agent-product-live-backtest.md)" in english
