from pathlib import Path

from klara.eval.runtime_integration import evaluate_runtime_integration, render_runtime_integration_markdown


ROOT = Path(__file__).parents[3]


def test_runtime_integration_gate_passes_without_faking_model_quality() -> None:
    report = evaluate_runtime_integration(ROOT)

    assert report["passed"]
    assert report["metrics"]["runtime_tool_count"] == 14
    assert report["metrics"]["unauthorized_mutations"] == 0
    assert report["metrics"]["authorized_mutations"] == 1
    assert "scripted model" in report["limitations"][0]
    assert report["checks"]["real_model_runtime_smoke_passes"]
    assert report["live_smoke"]["cases_passed"] == 3


def test_runtime_integration_reports_share_one_result() -> None:
    report = evaluate_runtime_integration(ROOT)
    for output in (
        render_runtime_integration_markdown(report),
        render_runtime_integration_markdown(report, language="en"),
    ):
        assert report["scorer_version"] not in output or report["passed"]
        assert "task_create" in output
        assert "ALLOW_TASK" in output
        assert "deepseek/deepseek-v4-flash" in output
