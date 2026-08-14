from __future__ import annotations

from klara.eval.memory_competitor_preflight import render_preflight_markdown


def test_preflight_report_does_not_turn_readiness_into_score() -> None:
    report = {
        "preflight_passed": True,
        "status": "external_execution_blocked",
        "scores_ready": False,
        "systems": {
            "mem0": {
                "source_contract_passed": True,
                "execution_ready": False,
                "execution_status": "blocked_external_dependencies",
                "blockers": ["embedding endpoint missing"],
            }
        },
    }
    rendered = render_preflight_markdown(report, language="en")
    assert "Competitor scores ready: `False`" in rendered
    assert "it is not a Mem0" in rendered
