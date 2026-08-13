"""Run the paid KlaraBench candidate only under a nonzero frozen budget."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from klara.eval.behavior_runtime import run_live_candidate_evaluation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--output-cost-per-million", type=float, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--review-queue-out", type=Path, required=True)
    parser.add_argument("--review-key-out", type=Path, required=True)
    return parser


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report, queue, key = run_live_candidate_evaluation(
        args.fixture,
        args.manifest,
        repository_root=args.repository_root.resolve(),
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    )
    _write(args.json_out, report)
    _write(args.review_queue_out, queue)
    _write(args.review_key_out, key)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "observations": report["counts"]["observations"],
                "human_review_items": len(queue),
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
