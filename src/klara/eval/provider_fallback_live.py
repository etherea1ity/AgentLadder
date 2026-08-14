"""Live Qwen-authentication to DeepSeek fallback evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from klara.core.messages import KlaraMessage
from klara.eval.provider_smoke import PROBE_NAME, PROBE_NONCE, PROBE_TOOL
from klara.infra.config.loader import load_models_config
from klara.infra.llm.openai_compatible import OpenAICompatibleSettings
from klara.infra.llm.routed_client import RoutedLlmClient


SCHEMA_VERSION = "klara.agent-product-provider-fallback-live.v1"
SYSTEM_PROMPT = (
    "This is a bounded public provider-fallback test. Call backtest_probe exactly "
    "once with the nonce supplied by the user. Do not reveal hidden reasoning."
)
USER_PROMPT = f"Call backtest_probe exactly once with nonce '{PROBE_NONCE}'."


def evaluate_provider_fallback_live(root: Path) -> dict[str, Any]:
    """Run one real routed request through the frozen agent profile."""

    models = load_models_config(root / "config")
    requested_model = models.profile("agent").primary
    client = RoutedLlmClient(
        models=models,
        settings=OpenAICompatibleSettings(
            max_tokens=96,
            temperature=0.0,
            timeout_seconds=60,
            retry_attempts=1,
            retry_base_delay_seconds=0.0,
            retry_max_delay_seconds=0.0,
        ),
        dotenv_path=str(root / ".env"),
    )
    started = perf_counter()
    response = client.complete(
        system_prompt=SYSTEM_PROMPT,
        messages=(KlaraMessage(role="user", content=USER_PROMPT),),
        tools=(PROBE_TOOL,),
        model=requested_model,
        thinking_enabled=False,
    )
    duration_ms = max(0, int((perf_counter() - started) * 1000))
    events = [
        {"type": event.type, "payload": event.payload}
        for event in response.runtime_events
    ]
    event_types = [item["type"] for item in events]
    calls = [
        {"id": call.id, "name": call.name, "arguments": call.arguments}
        for call in response.tool_calls
    ]
    failed = [item for item in events if item["type"] == "model_route.candidate_failed"]
    skipped = [item for item in events if item["type"] == "model_route.candidate_skipped"]
    completed = [
        item for item in events if item["type"] == "model_route.candidate_completed"
    ]
    checks = {
        "qwen_is_frozen_primary": requested_model.startswith("qwen/"),
        "qwen_auth_failure_is_typed": len(failed) == 1
        and failed[0]["payload"].get("error_code")
        == "provider_authentication_failed"
        and failed[0]["payload"].get("status_code") == 401,
        "qwen_siblings_are_skipped_after_auth_failure": bool(skipped)
        and all(
            item["payload"].get("reason")
            == "provider_authentication_circuit_open"
            for item in skipped
        ),
        "deepseek_fallback_completed": response.model_used is not None
        and response.model_used.startswith("deepseek/")
        and len(completed) == 1,
        "fallback_event_order_is_public": event_types.index(
            "model_route.candidate_failed"
        )
        < event_types.index("model_route.fallback_started")
        < event_types.index("model_route.candidate_completed"),
        "fallback_tool_call_is_exact": len(calls) == 1
        and calls[0]["name"] == PROBE_NAME
        and calls[0]["arguments"] == {"nonce": PROBE_NONCE},
        "usage_is_reported": int((response.usage or {}).get("total_tokens", 0)) > 0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": "ch08-provider-live-fallback",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "requested_model": requested_model,
        "model_used": response.model_used,
        "duration_ms": duration_ms,
        "usage": response.usage or {},
        "tool_calls": calls,
        "runtime_events": events,
        "checks": checks,
        "passed": all(checks.values()),
        "limitations": [
            "The configured Qwen credential was rejected with HTTP 401.",
            "This proves live fallback behavior, not Qwen availability or Qwen quality.",
            "DeepSeek cannot independently judge a DeepSeek candidate run.",
        ],
    }


def render_provider_fallback_live_markdown(
    report: dict[str, Any], *, language: str = "zh"
) -> str:
    """Render mirrored Chinese and English reports."""

    zh = language == "zh"
    title = "Chapter 8 真实供应商回退" if zh else "Chapter 8 Live Provider Fallback"
    toggle = (
        "语言：中文 | [English](./ch08-provider-live-fallback.en.md)"
        if zh
        else "Language: [Chinese](./ch08-provider-live-fallback.md) | English"
    )
    lines = [
        f"# {title}",
        "",
        toggle,
        "",
        f"- {'结论' if zh else 'Verdict'}: `{'通过' if report['passed'] and zh else 'PASS' if report['passed'] else '未通过' if zh else 'FAIL'}`",
        f"- {'请求模型' if zh else 'Requested model'}: `{report['requested_model']}`",
        f"- {'实际模型' if zh else 'Actual model'}: `{report['model_used']}`",
        f"- {'耗时' if zh else 'Duration'}: `{report['duration_ms']} ms`",
        "",
        f"## {'验收检查' if zh else 'Acceptance Checks'}",
        "",
        f"| {'检查' if zh else 'Check'} | {'结果' if zh else 'Result'} |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {key} | {'PASS' if value else 'FAIL'} |"
        for key, value in sorted(report["checks"].items())
    )
    lines.extend(
        [
            "",
            f"## {'公开运行事件' if zh else 'Public Runtime Events'}",
            "",
            "```json",
            json.dumps(report["runtime_events"], ensure_ascii=False, indent=2),
            "```",
            "",
            f"## {'边界' if zh else 'Boundaries'}",
            "",
        ]
    )
    if zh:
        lines.extend(
            [
                "- 当前千问凭证被服务端以 HTTP 401 拒绝。",
                "- 本报告只证明真实回退链，不证明千问可用性或质量。",
                "- DeepSeek 不能作为 DeepSeek 候选运行的独立裁判。",
            ]
        )
    else:
        lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)
