from pathlib import Path

from klara.eval.product_polish import evaluate_product_polish, render_product_polish_markdown


ROOT = Path(__file__).parents[3]


def test_product_polish_gate_passes_and_remains_honest() -> None:
    report = evaluate_product_polish(ROOT)

    assert report["passed"]
    assert report["metrics"]["checks_passed"] == report["metrics"]["checks_total"]
    assert report["metrics"]["p0_strange_response_count_after_repair"] == 0
    assert "not Agent Product Freeze" in report["limitations"][0]
    assert "HKU" in report["limitations"][-1]


def test_product_polish_bilingual_reports_come_from_same_result() -> None:
    report = evaluate_product_polish(ROOT)

    chinese = render_product_polish_markdown(report)
    english = render_product_polish_markdown(report, language="en")

    for output in (chinese, english):
        assert report["scorer_version"] in output
        assert f"{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}" in output
        assert "provider-dsml-leak" in output
        assert "cancel-tail-events" in output
