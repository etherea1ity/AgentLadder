from pathlib import Path

from klara.eval.chapter08 import evaluate_chapter08, render_chapter08_markdown


ROOT = Path(__file__).parents[3]


def test_chapter08_gate_exercises_fault_recovery_product_contract() -> None:
    report = evaluate_chapter08(ROOT)

    assert report["passed"] is True
    assert report["metrics"]["checks_passed"] == report["metrics"]["checks_total"]
    assert report["metrics"]["provider_attempts"] == 2
    assert report["metrics"]["prompt_recovery_attempts"] == 1


def test_chapter08_reports_have_mirrored_structure() -> None:
    report = evaluate_chapter08(ROOT)
    chinese = render_chapter08_markdown(report)
    english = render_chapter08_markdown(report, language="en")

    assert chinese.count("\n## ") == english.count("\n## ")
    assert "ch08-provider-recovery.en.md" in chinese
    assert "ch08-provider-recovery.md" in english
