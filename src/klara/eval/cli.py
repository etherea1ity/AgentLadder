"""Command-line gate for reproducible evidence and trajectory evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import tomllib
from typing import Any, Sequence

from klara.eval.dataset import DatasetValidation, validate_dataset
from klara.eval.scorers import evaluate_fixture
from klara.eval.trajectory import (
    canonical_json,
    export_jsonl,
    leakage_findings,
    load_jsonl,
    stable_sha256,
)


def run_gate(fixture_path: Path, config_path: Path):
    """Run the complete Lab A gate and return its immutable report."""

    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    if not isinstance(fixture, dict):
        raise ValueError("evaluation fixture must be a JSON object")
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    thresholds = config.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("evaluation config requires [thresholds]")

    trajectory_name = str(fixture.get("trajectory_file", ""))
    if not trajectory_name:
        raise ValueError("evaluation fixture requires trajectory_file")
    trajectory_path = fixture_path.parent / trajectory_name
    records = load_jsonl(trajectory_path)
    dataset = validate_dataset(records)
    configured_schema = str(config.get("schema_version", ""))
    if any(record.schema_version != configured_schema for record in records):
        raise ValueError("trajectory schema does not match evaluation config")
    configured_scorer = str(config.get("scorer_version", ""))
    if str(fixture.get("scorer_version", "")) != configured_scorer:
        raise ValueError("fixture scorer does not match evaluation config")
    fixture_leaks = tuple(
        sorted(leakage_findings(fixture, "$.fixture"))
    )
    if fixture_leaks:
        dataset = DatasetValidation(
            total_records=dataset.total_records,
            valid_records=dataset.valid_records,
            linkage_checks=dataset.linkage_checks,
            linkage_passed=dataset.linkage_passed,
            leakage_findings=dataset.leakage_findings + fixture_leaks,
        )
    with tempfile.TemporaryDirectory(prefix="klara-gate1-") as temporary:
        temporary_root = Path(temporary)
        first_hash = export_jsonl(records, temporary_root / "first.jsonl")
        second_hash = export_jsonl(records, temporary_root / "second.jsonl")

    fixture_hash = stable_sha256(canonical_json(fixture))
    trajectory_hash = stable_sha256(trajectory_path.read_bytes())
    return evaluate_fixture(
        fixture,
        dataset=dataset,
        fixture_sha256=fixture_hash,
        trajectory_sha256=trajectory_hash,
        deterministic_export_sha256=first_hash,
        deterministic_hash_match=first_hash == second_hash,
        thresholds={str(key): value for key, value in thresholds.items()},
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the small, stable command-line surface."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    gate = subparsers.add_parser("gate", help="run the Lab A acceptance gate")
    gate.add_argument("--fixture", type=Path, required=True)
    gate.add_argument("--config", type=Path, required=True)
    gate.add_argument("--json-out", type=Path, required=True)
    gate.add_argument("--markdown-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute a gate command and return a process status."""

    args = build_parser().parse_args(argv)
    if args.command != "gate":  # pragma: no cover - argparse owns command choices
        raise ValueError(f"unknown command: {args.command}")
    report = run_gate(args.fixture, args.config)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(report.to_json(), encoding="utf-8", newline="\n")
    args.markdown_out.write_text(
        report.to_markdown(),
        encoding="utf-8",
        newline="\n",
    )
    print(report.to_json(), end="")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
