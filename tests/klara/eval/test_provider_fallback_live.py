from __future__ import annotations

from klara.eval.provider_fallback_live import render_provider_fallback_live_markdown


def test_provider_fallback_live_markdown_has_mirrored_boundaries() -> None:
    report = {
        "passed": True,
        "requested_model": "qwen/qwen3.7-flash",
        "model_used": "deepseek/deepseek-v4-flash",
        "duration_ms": 10,
        "checks": {"deepseek_fallback_completed": True},
        "runtime_events": [],
        "limitations": ["one", "two", "three"],
    }

    zh = render_provider_fallback_live_markdown(report)
    en = render_provider_fallback_live_markdown(report, language="en")

    assert "真实供应商回退" in zh
    assert "当前千问凭证" in zh
    assert "Live Provider Fallback" in en
    assert "- three" in en
