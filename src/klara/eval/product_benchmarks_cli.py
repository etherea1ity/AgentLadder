"""Aggregate Agent Product Benchmark reports and write bilingual artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Sequence

from klara.eval.product_benchmarks import (
    build_human_review_status,
    build_product_benchmark_report,
    render_product_benchmark_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "manifest",
        "runtime-calibration",
        "locomo",
        "longmemeval",
        "memory-agent-bench",
        "public-agent",
        "memory-competitors",
        "json-out",
        "markdown-out",
        "markdown-en-out",
        "human-review-out",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--details-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_product_benchmark_report(
        manifest_path=args.manifest,
        runtime_calibration_path=args.runtime_calibration,
        locomo_path=args.locomo,
        longmemeval_path=args.longmemeval,
        memory_agent_bench_path=args.memory_agent_bench,
        public_agent_path=args.public_agent,
        memory_competitors_path=args.memory_competitors,
    )
    outputs = (
        args.json_out,
        args.markdown_out,
        args.markdown_en_out,
        args.human_review_out,
    )
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(_json(report), encoding="utf-8", newline="\n")
    args.markdown_out.write_text(
        render_product_benchmark_markdown(report), encoding="utf-8", newline="\n"
    )
    args.markdown_en_out.write_text(
        render_product_benchmark_markdown(report, language="en"),
        encoding="utf-8",
        newline="\n",
    )
    args.human_review_out.write_text(
        _json(build_human_review_status()), encoding="utf-8", newline="\n"
    )
    if args.details_dir is not None:
        args.details_dir.mkdir(parents=True, exist_ok=True)
        for source, filename in (
            (args.runtime_calibration, "agent-product-benchmarks-runtime-calibration.json"),
            (args.locomo, "agent-product-benchmarks-locomo.json"),
            (args.longmemeval, "agent-product-benchmarks-longmemeval.json"),
            (args.memory_agent_bench, "agent-product-benchmarks-memory-agent-bench.json"),
            (args.public_agent, "agent-product-benchmarks-public-agent-contracts.json"),
            (args.memory_competitors, "agent-product-benchmarks-memory-competitors.json"),
        ):
            shutil.copyfile(source, args.details_dir / filename)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "local_pre_freeze_ready": report["local_pre_freeze_ready"],
                "blockers": len(report["blockers"]),
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 2


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
