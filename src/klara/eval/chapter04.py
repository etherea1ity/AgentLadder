"""Machine-check the Chapter 4 harness and configuration acceptance contract."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from klara.app.cli import build_harness
from klara.infra.config.loader import load_models_config, load_runtime_config


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter04-harness-config.v1"


def evaluate_chapter04(root: Path) -> dict[str, Any]:
    """Evaluate the frozen Chapter 4 structure without provider calls."""

    config_dir = root / "config"
    models = load_models_config(config_dir)
    runtime = load_runtime_config(config_dir, env={})
    profile = runtime.profile()
    harness = build_harness(
        config_dir=config_dir,
        model=models.profile("agent").primary,
        thinking_enabled=None,
        trace_path=root / "data/traces/ch04-eval.jsonl",
    )
    public = harness.run_profile.to_public_dict()
    public_text = json.dumps(public, ensure_ascii=False, sort_keys=True).lower()
    api_source = (root / "apps/api/services/run_service.py").read_text(encoding="utf-8")
    cli_source = (root / "src/klara/app/cli.py").read_text(encoding="utf-8")
    checks = {
        "api_uses_harness": "KlaraHarness(" in api_source and "KlaraLoop(" not in api_source,
        "cli_uses_harness": "KlaraHarness(" in cli_source and "KlaraLoop(" not in cli_source,
        "profile_schema_frozen": public["schema_version"] == "klara.run-profile.v1",
        "profile_hash_valid": _profile_hash_valid(public),
        "persona_hash_valid": len(str(public["persona_sha256"])) == 64,
        "required_tools_visible": tuple(public["visible_tools"]) == profile.visible_tools,
        "hooks_and_trace_declared": (
            tuple(public["hooks"]) == ("permission_engine", *profile.hooks)
            and public["trace_sink"] == profile.trace_sink
        ),
        "model_supports_profile": _model_supports_profile(models, public["model"], profile.required_model_capabilities),
        "secret_values_absent": not any(marker in public_text for marker in ("api_key", "password", "secret", "bearer ")),
        "provider_connection_details_absent": not any(marker in public_text for marker in ("base_url", "api_key_env", "provider.invalid")),
        "stage_manifest_exists": (root / "config/stages/ch04-harness-config.manifest.json").exists(),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch04-harness-config",
        "gate_kind": "deterministic_product_gate",
        "run_profile": public,
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "configured_models": sum(len(provider.models) for provider in models.providers.values()),
            "visible_tools": len(public["visible_tools"]),
            "loop_max_turns": runtime.loop_policy.max_turns,
            "loop_max_tool_calls": runtime.loop_policy.max_tool_calls,
        },
        "interpretation": "Passing proves that local product entrypoints share one frozen, capability-checked, secret-free harness assembly. It does not test paid provider quality or later Agent chapters.",
        "passed": all(checks.values()),
    }


def render_chapter04_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    """Render Chinese or structurally identical English gate evidence."""

    english = language == "en"
    title = "Chapter 4 Harness and Config Gate" if english else "Chapter 4 Harness 与 Config 门禁"
    toggle = "Language: [Chinese](./ch04-harness-config.md) | English" if english else "语言：中文 | [English](./ch04-harness-config.en.md)"
    status = "PASS" if report["passed"] else "FAIL"
    lines = [
        f"# {title}", "", toggle, "", f"Status: **{status}**", "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Profile hash' if english else '运行快照 hash'}: `{report['run_profile']['profile_sha256']}`",
        f"- {'Model' if english else '模型'}: `{report['run_profile']['model']}`", "",
        f"## {'Acceptance Checks' if english else '验收检查'}", "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |", "| --- | --- |",
    ]
    lines.extend(f"| {key} | {'PASS' if value else 'FAIL'} |" for key, value in sorted(report["checks"].items()))
    lines.extend([
        "", f"## {'Frozen Profile' if english else '冻结运行快照'}", "", "```json",
        json.dumps(report["run_profile"], ensure_ascii=False, indent=2, sort_keys=True), "```", "",
        f"## {'Interpretation Boundary' if english else '解释边界'}", "",
        report["interpretation"] if english else "通过证明本地产品入口共享同一份不可变、经过能力检查且不含密钥的 harness 组装；它不评估付费模型质量，也不代表后续 Agent 章节已完成。", "",
    ])
    return "\n".join(lines)


def _profile_hash_valid(profile: dict[str, Any]) -> bool:
    payload = dict(profile)
    expected = payload.pop("profile_sha256", None)
    actual = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return expected == actual


def _model_supports_profile(models, model_ref: str, required: tuple[str, ...]) -> bool:
    provider_id, separator, model_id = model_ref.partition("/")
    if not separator or provider_id not in models.providers:
        return False
    model = models.providers[provider_id].model_entry(model_id)
    if model is None:
        return False
    supported = {"tools": model.supports_tools, "json": model.supports_json, "vision": model.supports_vision, "thinking": model.supports_thinking}
    return all(supported[item] for item in required)
