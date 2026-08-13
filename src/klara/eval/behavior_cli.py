"""CLI for the frozen Agent behavior evaluation contract and later candidate runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tomllib
from typing import Any, Sequence

from klara.eval.behavior import (
    BehaviorObservation,
    KlaraBehaviorCase,
    build_human_review_queue,
    load_fixture,
    score_observation,
    stable_hash,
)
from klara.eval.behavior_report import build_behavior_report, render_behavior_markdown
from klara.eval.documentation import discover_pairs, validate_pair


def run_contract_gate(
    fixture_path: Path,
    config_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Validate the evaluation substrate using explicit compliant control probes."""

    fixture = load_fixture(fixture_path)
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema_version") != "klara.behavior-case.v1":
        raise ValueError("behavior config schema does not match case schema")
    thresholds = config.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("behavior config requires [thresholds]")
    observations = [
        _compliant_control_observation(case, repetition)
        for case in fixture.cases
        for repetition in range(1, case.repetitions + 1)
    ]
    scores = [
        score_observation(case, observation)
        for case in fixture.cases
        for observation in observations
        if observation.case_id == case.case_id
    ]
    report = build_behavior_report(
        fixture,
        scores,
        thresholds={str(key): value for key, value in thresholds.items()},
        fixture_sha256=stable_hash(json.loads(fixture_path.read_text(encoding="utf-8"))),
    )
    pair_paths = discover_pairs(
        repository_root,
        [
            repository_root / "docs" / "chapters",
            repository_root / "docs" / "labs",
            repository_root / "docs" / "reports" / "product",
        ],
    )
    documentation = [
        validate_pair(repository_root, chinese, english).to_dict()
        for chinese, english in pair_paths
    ]
    review_queue = build_human_review_queue(fixture, observations)
    report.update(
        {
            "gate_kind": "contract_control_probe",
            "interpretation": "Validates schemas, graders, thresholds, split isolation, report rendering, and review plumbing. It does not measure the current Agent product.",
            "documentation": {
                "scorer_version": "klara.documentation-validator.v1",
                "pair_count": len(documentation),
                "results": documentation,
                "passed": all(bool(item["passed"]) for item in documentation),
            },
            "human_review_queue": {
                "count": len(review_queue),
                "items": review_queue,
            },
        }
    )
    report["checks"]["documentation_pairs"] = report["documentation"]["passed"]
    report["checks"]["human_review_queue_empty_after_control_labels"] = not review_queue
    report["passed"] = all(report["checks"].values())
    return report


def _compliant_control_observation(
    case: KlaraBehaviorCase, repetition: int
) -> BehaviorObservation:
    """Build a named control probe that exercises every required grader path."""

    return BehaviorObservation(
        case_id=case.case_id,
        repetition=repetition,
        final_answer=case.reference.answer,
        actions=list(case.reference.actions),
        states=list(case.expected_states),
        artifacts=list(case.expected_artifacts),
        invariant_results={invariant: True for invariant in case.invariants},
        latency_ms=min(50, case.limits.maximum_latency_ms),
        tokens=min(32, case.limits.maximum_tokens),
        cost_usd=0,
        reference_success=True,
        judge_outcome="equivalent",
        human_acceptable=True,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the evaluation CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument("--markdown-en-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the contract gate and write every format from one result object."""

    args = build_parser().parse_args(argv)
    report = run_contract_gate(
        args.fixture,
        args.config,
        repository_root=args.repository_root.resolve(),
    )
    for path in (args.json_out, args.markdown_out, args.markdown_en_out):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    args.markdown_out.write_text(
        render_behavior_markdown(report), encoding="utf-8", newline="\n"
    )
    args.markdown_en_out.write_text(
        render_behavior_markdown(report, language="en"),
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"passed": report["passed"], "gate_kind": report["gate_kind"], "observations": report["counts"]["observations"]}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
