from __future__ import annotations

from klara.eval.live_tooling_backtest import render_live_tooling_markdown


def test_live_tooling_markdown_preserves_model_and_case_results() -> None:
    report = {
        "passed": True,
        "model": "deepseek/deepseek-v4-flash",
        "metrics": {
            "cases_passed": 1,
            "cases_total": 1,
            "strange_response_p0_count": 0,
        },
        "cases": [
            {
                "case_id": "team-read-only-selection",
                "question": "List agents.",
                "reference_answer": "Zero.",
                "candidate_answer": "Zero.",
                "tool_names": ["team_list"],
                "passed": True,
            }
        ],
        "limitations": ["one", "two", "three"],
    }

    zh = render_live_tooling_markdown(report)
    en = render_live_tooling_markdown(report, language="en")

    assert "真实工具决策回测" in zh
    assert "team_list" in zh
    assert "Live Tool-Decision Backtest" in en
    assert "- three" in en
