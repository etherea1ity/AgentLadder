from __future__ import annotations

from klara.eval.public_memory_live import (
    locomo_exact_match,
    locomo_official_f1,
    render_memory_live_markdown,
)


def test_locomo_official_f1_matches_single_and_multi_answer_rules() -> None:
    assert locomo_official_f1("the blue bicycle", "blue bicycle", "2") == 1.0
    assert locomo_official_f1("Paris, London", "Paris, London", "1") == 1.0
    assert locomo_official_f1("May", "May; 2023", "3") == 1.0


def test_locomo_adversarial_and_exact_match_rules() -> None:
    assert locomo_official_f1("No information available.", "unknown", "5") == 1.0
    assert locomo_exact_match("The cat and dog", "dog cat") is True


def test_memory_live_renderer_uses_output_stem_for_bilingual_links() -> None:
    report = {
        "passed": True,
        "controls": {"model": "model", "max_output_tokens": 1, "top_k": 20},
        "selection": {"selected_questions": 0},
        "systems": {},
        "limitations": [],
    }

    zh = render_memory_live_markdown(report, output_stem="custom")
    en = render_memory_live_markdown(report, language="en", output_stem="custom")

    assert "(./custom.en.md)" in zh
    assert "(./custom.md)" in en
