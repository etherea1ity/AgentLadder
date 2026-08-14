from __future__ import annotations

import json
from pathlib import Path

from klara.core.messages import ModelResponse
from klara.core.tools import ToolCall
from klara.eval.provider_smoke import (
    PROBE_NAME,
    PROBE_NONCE,
    evaluate_provider_smoke,
    render_provider_smoke_markdown,
)


def test_provider_smoke_requires_exact_models_tools_usage_and_budget(tmp_path: Path) -> None:
    manifest = {
        "authorization": {"paid_api_calls": True},
        "model_roles": {
            "candidate_a": "deepseek/deepseek-v4-flash",
            "candidate_b": "qwen/qwen3.7-flash",
        },
        "budgets": {
            "maximum_total_requests": 2,
            "maximum_deepseek_usd": 1,
            "maximum_qwen_cny": 1,
        },
        "pricing": {
            "deepseek_usd_per_million_tokens": {
                "deepseek-v4-flash": {"input_cache_miss": 0.14, "output": 0.28}
            },
            "qwen_cny_list_price_per_million_tokens": {
                "qwen3.7-flash_0_to_32k": {"input": 0.2, "output": 0.8}
            },
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.toml").write_text("", encoding="utf-8")

    def complete(model: str) -> ModelResponse:
        return ModelResponse(
            content="",
            tool_calls=(
                ToolCall(
                    id=f"call-{model}",
                    name=PROBE_NAME,
                    arguments={"nonce": PROBE_NONCE},
                ),
            ),
            usage={"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            model_used=model,
        )

    report = evaluate_provider_smoke(tmp_path, manifest_path=manifest_path, complete=complete)

    assert report["passed"] is True
    assert report["request_count"] == 2
    assert report["native_costs"]["USD"] > 0
    assert report["native_costs"]["CNY"] > 0
    assert all(case["tool_call_valid"] for case in report["cases"])


def test_provider_smoke_rejects_fallback_identity(tmp_path: Path) -> None:
    manifest = {
        "authorization": {},
        "model_roles": {
            "candidate_a": "deepseek/deepseek-v4-flash",
            "candidate_b": "qwen/qwen3.7-flash",
        },
        "budgets": {
            "maximum_total_requests": 2,
            "maximum_deepseek_usd": 1,
            "maximum_qwen_cny": 1,
        },
        "pricing": {
            "deepseek_usd_per_million_tokens": {
                "deepseek-v4-flash": {"input_cache_miss": 0.14, "output": 0.28}
            },
            "qwen_cny_list_price_per_million_tokens": {
                "qwen3.7-flash_0_to_32k": {"input": 0.2, "output": 0.8}
            },
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/models.toml").write_text("", encoding="utf-8")

    response = ModelResponse(
        content="",
        tool_calls=(ToolCall(id="call", name=PROBE_NAME, arguments={"nonce": PROBE_NONCE}),),
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        model_used="deepseek/deepseek-v4-pro",
    )
    report = evaluate_provider_smoke(
        tmp_path,
        manifest_path=manifest_path,
        complete=lambda _: response,
    )

    assert report["passed"] is False
    assert report["checks"]["all_exact_models_completed"] is False


def test_provider_smoke_renderer_uses_requested_bilingual_names() -> None:
    report = {
        "passed": True,
        "request_count": 0,
        "native_costs": {},
        "cases": [],
        "limitations": [],
    }

    zh = render_provider_smoke_markdown(
        report, chinese_name="custom.md", english_name="custom.en.md"
    )
    en = render_provider_smoke_markdown(
        report,
        language="en",
        chinese_name="custom.md",
        english_name="custom.en.md",
    )

    assert "(./custom.en.md)" in zh
    assert "(./custom.md)" in en
