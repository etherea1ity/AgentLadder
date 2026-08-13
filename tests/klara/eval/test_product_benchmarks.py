"""Aggregation rules for the Agent Product Benchmark gate."""

from __future__ import annotations

from klara.eval.product_benchmarks import build_human_review_status, render_product_benchmark_markdown


def test_human_review_status_never_invents_candidate_labels() -> None:
    status = build_human_review_status()

    assert status["status"] == "not_generated"
    assert status["blind_review_pairs"] == 0
    assert status["candidate_slot_exposed"] is False


def test_markdown_keeps_failed_external_gates_visible() -> None:
    report = {
        "passed": False,
        "local_checks": {"local": True},
        "mandatory_product_checks": {"human": False},
        "metrics": {"observations": 41},
        "blockers": [{"id": "human", "detail": "missing", "needed": "review"}],
    }

    markdown = render_product_benchmark_markdown(report, language="en")

    assert "Status: **FAIL**" in markdown
    assert "| `human` | FAIL |" in markdown
    assert "No general ChatGPT parity" in markdown
