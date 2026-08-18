"""Run the local Klara MoE adapter through the unified eval harness."""
from __future__ import annotations

import argparse, json, tomllib
from pathlib import Path

from klara.eval.three_way_eval import EvalHarness, Pricing, evaluate, load_eval_bundle
from klara.eval.klara_adapter import KlaraModelAdapter


def _table(raw, key):
    v = raw.get(key, {})
    return v if isinstance(v, dict) else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    raw = tomllib.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    model = str(raw["model"])
    benchmark, backend = load_eval_bundle(Path(raw["benchmark_fixture"]))

    h = _table(raw, "harness")
    p = _table(raw, "pricing")
    harness = EvalHarness(
        backend=backend,
        max_steps=int(h.get("max_steps", 8)),
        max_tokens=int(h.get("max_tokens", 512)),
        temperature=float(h.get("temperature", 0.0)),
        timeout_seconds=int(h.get("timeout_seconds", 120)),
        retry_attempts=int(h.get("retry_attempts", 2)),
        retry_base_delay_seconds=float(h.get("retry_base_delay_seconds", 0.0)),
        retry_max_delay_seconds=float(h.get("retry_max_delay_seconds", 0.0)),
        ordered_tool_calls=bool(h.get("ordered_tool_calls", False)),
        pricing=Pricing(
            currency=str(p.get("currency", "USD")),
            input_usd_per_million=float(p.get("input_usd_per_million", 0.0)),
            output_usd_per_million=float(p.get("output_usd_per_million", 0.0)),
        ),
        root=Path("."),
    )
    adapter = KlaraModelAdapter(model=model, checkpoint=args.checkpoint, max_new_tokens=harness.max_tokens)
    report = evaluate(model, benchmark, harness, adapter=adapter)

    out = Path(args.output) if args.output else Path(str(raw.get("results_dir", "results"))) / "klara-dev.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    m = report["metrics"]
    print(f"model: {model}")
    print(f"tasks: {report['counts']['tasks']}")
    print(f"task_success: {m['task_success']:.4f}")
    print(f"tool_call_accuracy: {m['tool_call_accuracy']:.4f}")
    print(f"invalid_call_rate: {m['invalid_call_rate']:.4f}")
    print(f"output: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
