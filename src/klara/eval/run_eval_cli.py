"""CLI for running the unified three-way evaluation harness.

Usage::

    python -m klara.eval.run_eval_cli --config config/eval/three_way_deepseek_smoke.toml

The CLI never prints API keys or dotenv contents.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib
from typing import Any

from klara.eval.three_way_eval import (
    EvalHarness,
    Pricing,
    evaluate,
    load_eval_bundle,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _resolve_path(value: str, *, root: Path, config_dir: Path) -> Path:
    """Resolve a config path against the config dir, then the repo root."""

    path = Path(value)
    if path.is_absolute():
        return path
    if (config_dir / path).exists():
        return config_dir / path
    return root / path


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def _table(raw: Any, key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a table")
    return value


def _int_config(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return int(value)


def _float_config(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _bool_config(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to eval config TOML")
    parser.add_argument(
        "--model",
        default=None,
        help="Optional model override, e.g. deepseek/deepseek-v4-pro",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output JSON path override",
    )
    args = parser.parse_args(argv)

    config_path = _resolve_path(
        args.config,
        root=REPOSITORY_ROOT,
        config_dir=Path.cwd(),
    )
    raw = _load_toml(config_path)
    config_dir = config_path.parent

    model = args.model or str(raw["model"])
    fixture_path = _resolve_path(
        str(raw["benchmark_fixture"]),
        root=REPOSITORY_ROOT,
        config_dir=config_dir,
    )
    benchmark, backend = load_eval_bundle(fixture_path)

    harness_raw = _table(raw, "harness")
    pricing_raw = _table(raw, "pricing")
    harness = EvalHarness(
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
        ordered_tool_calls=_bool_config(
            harness_raw, "ordered_tool_calls", False
        ),
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

    report = evaluate(model, benchmark, harness)

    results_dir = _resolve_path(
        str(raw.get("results_dir", "results")),
        root=REPOSITORY_ROOT,
        config_dir=config_dir,
    )
    if args.output:
        output_path = _resolve_path(
            args.output,
            root=REPOSITORY_ROOT,
            config_dir=config_dir,
        )
    else:
        output_name = model.replace("/", "-").replace("\\", "-") + ".json"
        output_path = results_dir / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    metrics = report["metrics"]
    print(f"model: {model}")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
