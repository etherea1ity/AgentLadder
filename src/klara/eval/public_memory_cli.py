"""Run a pinned public Memory benchmark adapter and write JSON evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.public_memory import (
    evaluate_locomo_checkout,
    run_longmemeval_oracle_contract,
    run_memory_agent_bench_contract,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--locomo-checkout", type=Path)
    source.add_argument("--longmemeval-oracle", type=Path)
    source.add_argument("--memory-agent-bench-cache", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.locomo_checkout is not None:
        report = evaluate_locomo_checkout(args.locomo_checkout.resolve())
    elif args.longmemeval_oracle is not None:
        report = run_longmemeval_oracle_contract(args.longmemeval_oracle.resolve())
    else:
        report = run_memory_agent_bench_contract(args.memory_agent_bench_cache.resolve())
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "benchmark": report["benchmark"],
                "passed": report["passed"],
                "selected_questions": report.get("selection", {}).get(
                    "selected_questions",
                    report.get("selection", {}).get("sample_size", 0),
                ),
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
