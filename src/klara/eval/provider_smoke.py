"""Bounded live provider and tool-call smoke for the product backtest."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolSpec
from klara.infra.config.loader import load_models_config
from klara.infra.llm.model_ref import ModelRef
from klara.infra.llm.openai_compatible import (
    LlmProviderError,
    OpenAICompatibleLlmClient,
    OpenAICompatibleSettings,
)


SCHEMA_VERSION = "klara.agent-product-provider-smoke.v1"
PROBE_NAME = "backtest_probe"
PROBE_NONCE = "klara-live-backtest-v1"
SYSTEM_PROMPT = (
    "This is a bounded public agent-runtime connectivity test. Call the supplied "
    "backtest_probe tool exactly once with the exact nonce from the user. Do not "
    "invent another tool and do not reveal hidden reasoning."
)
USER_PROMPT = (
    "Call backtest_probe exactly once with nonce 'klara-live-backtest-v1'. "
    "Return a tool call now."
)
PROBE_TOOL = ToolSpec(
    name=PROBE_NAME,
    description="Record a harmless provider connectivity nonce.",
    input_schema={
        "type": "object",
        "properties": {"nonce": {"type": "string"}},
        "required": ["nonce"],
        "additionalProperties": False,
    },
)


Complete = Callable[[str], ModelResponse]


def evaluate_provider_smoke(
    root: Path,
    *,
    manifest_path: Path,
    complete: Complete | None = None,
) -> dict[str, Any]:
    """Call both frozen candidate models once and verify a real tool request."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    models = (
        str(manifest["model_roles"]["candidate_a"]),
        str(manifest["model_roles"]["candidate_b"]),
    )
    requested_at = datetime.now(UTC).isoformat()
    cases = []
    for model in models:
        cases.append(
            _run_case(
                root,
                model=model,
                complete=complete,
                manifest=manifest,
            )
        )

    checks = {
        "exactly_two_frozen_candidates": len(cases) == 2,
        "all_requests_completed": all(case["status"] == "completed" for case in cases),
        "all_exact_models_completed": all(
            case["model_used"] == case["requested_model"] for case in cases
        ),
        "all_exact_tool_calls": all(case["tool_call_valid"] for case in cases),
        "all_usage_reported": all(case["usage"]["total_tokens"] > 0 for case in cases),
        "no_provider_hidden_reasoning_collected": all(
            case["provider_hidden_reasoning_collected"] is False for case in cases
        ),
        "native_budget_below_declared_limits": _within_budget(cases, manifest),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": "agent-product-live-backtest-provider-smoke",
        "evaluated_at": requested_at,
        "manifest_sha256": _sha256(manifest_path),
        "models_config_sha256": _sha256(root / "config/models.toml"),
        "authorization": manifest["authorization"],
        "request_count": len(cases),
        "prompt": {
            "system_sha256": _text_sha256(SYSTEM_PROMPT),
            "user_sha256": _text_sha256(USER_PROMPT),
            "encoding": "utf-8",
        },
        "checks": checks,
        "cases": cases,
        "native_costs": _native_costs(cases),
        "provider_hidden_reasoning_collected": False,
        "passed": all(checks.values()),
        "limitations": [
            "This proves live identity, authentication, usage reporting, and one structured tool call only.",
            "It is not a product behavior score, a chapter pass, or a GPT-parity claim.",
        ],
    }


def _run_case(
    root: Path,
    *,
    model: str,
    complete: Complete | None,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    started = perf_counter()
    try:
        response = complete(model) if complete is not None else _live_complete(root, model)
        calls = [call.to_public_dict(include_arguments=True) for call in response.tool_calls]
        valid = (
            len(calls) == 1
            and calls[0]["name"] == PROBE_NAME
            and calls[0]["arguments"] == {"nonce": PROBE_NONCE}
        )
        usage = _normalized_usage(response.usage)
        return {
            "requested_model": model,
            "model_used": response.model_used,
            "status": "completed",
            "tool_calls": calls,
            "tool_call_valid": valid,
            "public_content": response.content,
            "usage": usage,
            "native_cost": _cost(model, usage, manifest),
            "duration_ms": max(0, int((perf_counter() - started) * 1000)),
            "provider_hidden_reasoning_collected": False,
            "error": None,
        }
    except (LlmProviderError, OSError, ValueError, KeyError) as exc:
        return {
            "requested_model": model,
            "model_used": None,
            "status": "failed",
            "tool_calls": [],
            "tool_call_valid": False,
            "public_content": "",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "native_cost": _zero_cost(model),
            "duration_ms": max(0, int((perf_counter() - started) * 1000)),
            "provider_hidden_reasoning_collected": False,
            "error": {
                "type": type(exc).__name__,
                "code": getattr(exc, "code", "provider_smoke_failed"),
                "status_code": getattr(exc, "status_code", None),
            },
        }


def _live_complete(root: Path, model: str) -> ModelResponse:
    configs = load_models_config(root / "config")
    model_ref = ModelRef.parse(model)
    provider = configs.providers[model_ref.provider]
    client = OpenAICompatibleLlmClient(
        provider_id=model_ref.provider,
        provider=provider,
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
    return client.complete(
        system_prompt=SYSTEM_PROMPT,
        messages=(KlaraMessage(role="user", content=USER_PROMPT),),
        tools=(PROBE_TOOL,),
        model=model,
        thinking_enabled=False,
    )


def _normalized_usage(usage: dict[str, int] | None) -> dict[str, int]:
    source = usage or {}
    prompt = int(source.get("prompt_tokens", 0))
    completion = int(source.get("completion_tokens", 0))
    total = int(source.get("total_tokens", prompt + completion))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _cost(model: str, usage: dict[str, int], manifest: dict[str, Any]) -> dict[str, Any]:
    pricing = manifest["pricing"]
    model_ref = ModelRef.parse(model)
    if model_ref.provider == "deepseek":
        rates = pricing["deepseek_usd_per_million_tokens"][model_ref.model]
        amount = (
            usage["prompt_tokens"] * float(rates["input_cache_miss"])
            + usage["completion_tokens"] * float(rates["output"])
        ) / 1_000_000
        return {"currency": "USD", "amount": round(amount, 8)}
    rates = pricing["qwen_cny_list_price_per_million_tokens"][f"{model_ref.model}_0_to_32k"]
    amount = (
        usage["prompt_tokens"] * float(rates["input"])
        + usage["completion_tokens"] * float(rates["output"])
    ) / 1_000_000
    return {"currency": "CNY", "amount": round(amount, 8)}


def _zero_cost(model: str) -> dict[str, Any]:
    return {
        "currency": "USD" if ModelRef.parse(model).provider == "deepseek" else "CNY",
        "amount": 0.0,
    }


def _native_costs(cases: list[dict[str, Any]]) -> dict[str, float]:
    totals = {"USD": 0.0, "CNY": 0.0}
    for case in cases:
        cost = case["native_cost"]
        totals[str(cost["currency"])] += float(cost["amount"])
    return {currency: round(amount, 8) for currency, amount in totals.items()}


def _within_budget(cases: list[dict[str, Any]], manifest: dict[str, Any]) -> bool:
    totals = _native_costs(cases)
    limits = manifest["budgets"]
    return (
        totals["USD"] <= float(limits["maximum_deepseek_usd"])
        and totals["CNY"] <= float(limits["maximum_qwen_cny"])
        and len(cases) <= int(limits["maximum_total_requests"])
    )


def render_provider_smoke_markdown(
    report: dict[str, Any],
    *,
    language: str = "zh",
    chinese_name: str = "agent-product-live-provider-smoke.md",
    english_name: str = "agent-product-live-provider-smoke.en.md",
) -> str:
    """Render the exact JSON smoke object as a compact bilingual report."""

    zh = language == "zh"
    title = "Agent 产品真实 Provider 冒烟" if zh else "Agent Product Live Provider Smoke"
    language_line = (
        f"语言：中文 | [English](./{english_name})"
        if zh
        else f"Language: [Chinese](./{chinese_name}) | English"
    )
    verdict = "通过" if report["passed"] and zh else "PASS" if report["passed"] else "未通过" if zh else "FAIL"
    lines = [
        f"# {title}",
        "",
        language_line,
        "",
        f"- {'结论' if zh else 'Verdict'}: `{verdict}`",
        f"- {'请求数' if zh else 'Requests'}: `{report['request_count']}`",
        f"- {'原生成本' if zh else 'Native cost'}: `{json.dumps(report['native_costs'], ensure_ascii=False, sort_keys=True)}`",
        "",
        f"## {'逐模型结果' if zh else 'Per-model results'}",
        "",
    ]
    for case in report["cases"]:
        lines.extend(
            [
                f"### {case['requested_model']}",
                "",
                f"- status: `{case['status']}`",
                f"- model_used: `{case['model_used']}`",
                f"- tool_call_valid: `{str(case['tool_call_valid']).lower()}`",
                f"- usage: `{json.dumps(case['usage'], sort_keys=True)}`",
                f"- cost: `{json.dumps(case['native_cost'], sort_keys=True)}`",
                f"- duration_ms: `{case['duration_ms']}`",
                "",
            ]
        )
    lines.extend(
        [
            f"## {'边界' if zh else 'Boundary'}",
            "",
            *[f"- {item}" for item in report["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
