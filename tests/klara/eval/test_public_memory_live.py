from __future__ import annotations

from klara.eval.public_memory_live import (
    locomo_exact_match,
    locomo_official_f1,
)


def test_locomo_official_f1_matches_single_and_multi_answer_rules() -> None:
    assert locomo_official_f1("the blue bicycle", "blue bicycle", "2") == 1.0
    assert locomo_official_f1("Paris, London", "Paris, London", "1") == 1.0
    assert locomo_official_f1("May", "May; 2023", "3") == 1.0


def test_locomo_adversarial_and_exact_match_rules() -> None:
    assert locomo_official_f1("No information available.", "unknown", "5") == 1.0
    assert locomo_exact_match("The cat and dog", "dog cat") is True
