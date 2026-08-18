"""Run the dev-fixture baselines.

DeepSeek is run live through ``evaluate`` using the key named by
``.env`` (the key value is never printed). Qwen ``no_finetune`` is currently a
config-only preflight because its weights live on HKU; this script validates
the route and writes a ``pending_hku_weights`` report without calling Qwen.

Typical use::

    python src/klara/eval/run_baseline_dev.py
    python src/klara/eval/run_baseline_dev.py --smoke
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from klara.eval.run_eval_cli import (  # noqa: E402
    _bool_config,
    _float_config,
    _int_config,
    _load_toml,
    _resolve_path,
    _table,
)
from klara.eval.three_way_eval import (  # noqa: E402
    EvalBenchmark,
    EvalHarness,
    Pricing,
    evaluate,
    load_eval_bundle,
)
from klara.infra.config.loader import load_models_config  # noqa: E402
from klara.infra.llm.model_ref import ModelRef  # noqa: E402

DEEPSEEK_CONFIG = REPOSITORY_ROOT / "config" / "eval" / "dev_deepseek.toml"
QWEN_CONFIG = REPOSITORY_ROOT / "config" / "eval" / "dev_qwen_nofinetune.toml"
DEEPSEEK_OUTPUT = REPOSITORY_ROOT / "results" / "deepseek-dev.json"
DEEPSEEK_SMOKE_OUTPUT = REPOSITORY_ROOT / "results" / "deepseek-dev-smoke.json"
QWEN_OUTPUT = REPOSITORY_ROOT / "results" / "qwen-nofinetune-dev.json"

SMOKE_TASK_IDS = (
    "eval_toolbench_single_tool_0003",  # current_time Africa/Abidjan
    "eval_bfcl_single_tool_0006",       # skills_list
    "eval_toolbench_single_tool_0007",  # skill_view repo_ops
)


def _resolve_eval_path(value: str, *, config_dir: Path) -> Path:
    return _resolve_path(value, root=REPOSITORY_ROOT, config_dir=config_dir)


def _load_config_and_bundle(
    config_path: Path,
    *,
    task_ids: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> tuple[dict[str, Any], EvalBenchmark, Any]:
    raw = _load_toml(config_path)
    config_dir = config_path.parent
    fixture_path = _resolve_eval_path(str(raw["benchmark_fixture"]), config_dir=config_dir)
    benchmark, backend = load_eval_bundle(fixture_path)

    selected: list[Any] = []
    if task_ids:
        by_id = {task.id: task for task in benchmark.tasks}
        missing = [task_id for task_id in task_ids if task_id not in by_id]
        if missing:
            raise ValueError(f"task ids not found in fixture: {', '.join(missing)}")
        selected = [by_id[task_id] for task_id in task_ids]
    elif limit is not None:
        if limit < 1:
            raise ValueError("--limit must be at least 1")
        selected = list(benchmark.tasks[:limit])

    if selected:
        benchmark = dataclasses.replace(benchmark, tasks=tuple(selected))
    return raw, benchmark, backend


def _build_harness(raw: dict[str, Any], backend: Any) -> EvalHarness:
    harness_raw = _table(raw, "harness")
    pricing_raw = _table(raw, "pricing")
    return EvalHarness(
        backend=backend,
        max_steps=_int_config(harness_raw, "max_steps", 8),
        max_tokens=_int_config(harness_raw, "max_tokens", 512),
        temperature=_float_config(harness_raw, "temperature", 0.0),
        timeout_seconds=_int_config(harness_raw, "timeout_seconds", 120),
        retry_attempts=_int_config(harness_raw, "retry_attempts", 2),
        retry_base_delay_seconds=_float_config(
            harness_raw, "retry_base_delay_seconds", 0.0
        ),
        retry_max_delay_seconds=_float_config(
            harness_raw, "retry_max_delay_seconds", 0.0
        ),
        ordered_tool_calls=_bool_config(harness_raw, "ordered_tool_calls", False),
        pricing=Pricing(
            currency=str(pricing_raw.get("currency", "USD")),
            input_usd_per_million=_float_config(
                pricing_raw, "input_usd_per_million", 0.0
            ),
            output_usd_per_million=_float_config(
                pricing_raw, "output_usd_per_million", 0.0
            ),
        ),
        root=REPOSITORY_ROOT,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_dotenv_key_names() -> set[str]:
    env_path = REPOSITORY_ROOT / ".env"
    if not env_path.exists():
        return set()
    names: set[str] = set()
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        names.add(line.split("=", 1)[0].strip())
    return names


def _print_deepseek_summary(report: dict[str, Any], output_path: Path) -> None:
    metrics = report["metrics"]
    print(f"model: {report['model']}")
    print(f"adapter_model: {report['adapter_model']}")
    print(f"benchmark: {report['benchmark']}")
    print(f"tasks: {report['counts']['tasks']}")
    print(f"task_success: {metrics['task_success']:.4f}")
    print(f"tool_call_accuracy: {metrics['tool_call_accuracy']:.4f}")
    print(f"invalid_call_rate: {metrics['invalid_call_rate']:.4f}")
    print(
        "token_usage: "
        f"prompt={metrics['token_usage']['prompt_tokens']}, "
        f"completion={metrics['token_usage']['completion_tokens']}, "
        f"total={metrics['token_usage']['total_tokens']}"
    )
    print(f"latency: total={metrics['latency']['total_ms']}ms, mean={metrics['latency']['mean_ms']:.1f}ms")
    print(f"cost: {metrics['cost']['amount_usd']} {metrics['cost']['currency']}")
    print(f"output: {output_path}")


def _run_deepseek(
    *,
    task_ids: tuple[str, ...] | None,
    limit: int | None,
    output_path: Path,
    model: str | None,
) -> dict[str, Any]:
    raw, benchmark, backend = _load_config_and_bundle(
        DEEPSEEK_CONFIG,
        task_ids=task_ids,
        limit=limit,
    )
    model = model or str(raw["model"])
    harness = _build_harness(raw, backend)
    report = evaluate(model, benchmark, harness)
    _write_json(output_path, report)
    _print_deepseek_summary(report, output_path)
    return report


def _run_qwen_preflight() -> dict[str, Any]:
    raw, benchmark, _ = _load_config_and_bundle(QWEN_CONFIG)
    model = str(raw["model"])
    model_ref = ModelRef.parse(model)
    if model_ref.provider != "qwen":
        raise ValueError(f"qwen no_finetune config must use a qwen model, got {model}")

    models_config = load_models_config(REPOSITORY_ROOT / "config")
    provider = models_config.providers.get("qwen")
    if provider is None:
        raise ValueError("qwen provider missing from config/models.toml")
    model_listed = provider.has_model(model_ref.model)
    dotenv_keys = _read_dotenv_key_names()
    api_key_configured = provider.api_key_env in dotenv_keys

    validation = {
        "schema_version": "klara.three-way-eval.v1",
        "model": model,
        "model_provider": model_ref.provider,
        "model_listed": model_listed,
        "fixture": str(_resolve_eval_path(str(raw["benchmark_fixture"]), config_dir=QWEN_CONFIG.parent)),
        "fixture_tasks": len(benchmark.tasks),
        "fixture_tools": len(benchmark.tools),
        "api_key_configured": api_key_configured,
    }
    report = {
        "schema_version": "klara.three-way-eval.v1",
        "model": model,
        "status": "pending_hku_weights",
        "validated": True,
        "validation": validation,
        "note": (
            "Qwen no_finetune weights live on HKU. This preflight validates the "
            "route but does not call the Qwen API; run the live eval after the "
            "weights are staged locally."
        ),
    }
    _write_json(QWEN_OUTPUT, report)
    print(f"qwen no_finetune: config preflight passed -> {QWEN_OUTPUT}")
    print(f"  api key env present: {api_key_configured} (value not printed)")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("all", "deepseek", "qwen"),
        default="all",
        help="Which baseline routes to produce (default: all)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run only three deterministic single-tool DeepSeek tasks",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N dev tasks for DeepSeek",
    )
    parser.add_argument(
        "--task-ids",
        default=None,
        help="Comma-separated dev task ids for DeepSeek",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional DeepSeek model override",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional DeepSeek output JSON path override",
    )
    args = parser.parse_args(argv)

    task_ids: tuple[str, ...] | None = None
    if args.smoke:
        task_ids = SMOKE_TASK_IDS
    elif args.task_ids:
        task_ids = tuple(part.strip() for part in args.task_ids.split(",") if part.strip())

    deepseek_output = (
        Path(args.output)
        if args.output
        else (DEEPSEEK_SMOKE_OUTPUT if (args.smoke or task_ids or args.limit) else DEEPSEEK_OUTPUT)
    )

    if args.target in {"all", "deepseek"}:
        _run_deepseek(
            task_ids=task_ids,
            limit=None if task_ids else args.limit,
            output_path=deepseek_output,
            model=args.model,
        )

    if args.target in {"all", "qwen"}:
        _run_qwen_preflight()

    return 0


if __name__ == "__main__":
    sys.exit(main())
