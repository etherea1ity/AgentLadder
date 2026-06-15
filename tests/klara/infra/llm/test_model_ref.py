from __future__ import annotations

import pytest

from klara.infra.llm.model_ref import ModelRef


def test_model_ref_parses_provider_and_model() -> None:
    """Model refs should use the same provider/model shape as ReAct."""

    ref = ModelRef.parse("deepseek/deepseek-v4-flash")

    assert ref.provider == "deepseek"
    assert ref.model == "deepseek-v4-flash"
    assert str(ref) == "deepseek/deepseek-v4-flash"


def test_model_ref_rejects_missing_provider_or_model() -> None:
    """Malformed model refs should fail before provider calls."""

    with pytest.raises(ValueError):
        ModelRef.parse("deepseek-v4-flash")
