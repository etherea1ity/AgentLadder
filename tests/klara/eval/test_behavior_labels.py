"""External label merge tests that prevent partial or unblinded gate scores."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from klara.eval.behavior import (
    BehaviorObservation,
    build_human_review_key,
    build_human_review_queue,
    load_fixture,
    score_observation,
    stable_hash,
)
from klara.eval.behavior_labels import LABEL_SCHEMA_VERSION, merge_external_labels
from klara.eval.behavior_report import build_behavior_report


ROOT = Path(__file__).parents[3]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "behavior" / "agent_behavior_cases.v2.json"
MANIFEST_PATH = ROOT / "config" / "stages" / "agent-product-benchmarks.manifest.json"


def _artifacts() -> tuple[dict, dict, dict]:
    fixture = load_fixture(FIXTURE_PATH)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    observations = [
        BehaviorObservation(
            case_id=case.case_id,
            repetition=repetition,
            final_answer=case.reference.answer,
            actions=case.reference.actions,
            states=case.expected_states,
            artifacts=case.expected_artifacts,
            invariant_results={name: True for name in case.invariants},
            latency_ms=1,
            tokens=1,
            cost_usd=0,
        )
        for case in fixture.cases
        for repetition in range(1, case.repetitions + 1)
    ]
    cases = {case.case_id: case for case in fixture.cases}
    fixture_sha256 = stable_hash(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
    candidate = build_behavior_report(
        fixture,
        [score_observation(cases[item.case_id], item) for item in observations],
        thresholds=manifest["thresholds"],
        fixture_sha256=fixture_sha256,
    )
    candidate.update(
        {
            "thresholds": manifest["thresholds"],
            "observations": [item.model_dump(mode="json") for item in observations],
            "runner_version": "test-runner",
            "model": "test-candidate",
            "runtime_runs": [
                {
                    "case_id": item.case_id,
                    "repetition": item.repetition,
                    "comparison_contract_sha256": stable_hash(
                        cases[item.case_id].model_dump(mode="json")
                    ),
                    "run_profile_sha256": "1" * 64,
                }
                for item in observations
            ],
        }
    )
    key = build_human_review_key(fixture, observations)
    queue = build_human_review_queue(fixture, observations)
    labels = {
        "schema_version": LABEL_SCHEMA_VERSION,
        "candidate_report_sha256": stable_hash(candidate),
        "provenance": {
            "reference": "independent-live-reference-run/test",
            "judge": "independent-model-judge/test",
            "human": "blind-human-panel/test",
        },
        "reference_results": [
            {
                "case_id": item.case_id,
                "repetition": item.repetition,
                "task_success": True,
                "comparison_contract_sha256": stable_hash(
                    cases[item.case_id].model_dump(mode="json")
                ),
                "run_artifact_sha256": "2" * 64,
            }
            for item in observations
        ],
        "judge_results": [
            {
                "case_id": item.case_id,
                "repetition": item.repetition,
                "outcome": "equivalent",
                "judge_artifact_sha256": "3" * 64,
            }
            for item in observations
        ],
        "human_reviews": [
            {
                "pair_id": row["pair_id"],
                "answer_a_acceptable": True,
                "answer_b_acceptable": True,
            }
            for row in queue
        ],
    }
    return candidate, labels, key


def test_external_labels_merge_only_after_exact_blind_coverage() -> None:
    candidate, labels, key = _artifacts()

    report = merge_external_labels(FIXTURE_PATH, candidate, labels, key)

    assert report["passed"]
    assert report["counts"]["judge_scored"] == report["counts"]["expected_observations"]
    assert report["counts"]["human_scored"] == report["counts"]["expected_observations"]
    assert report["checks"]["reference_non_inferiority"]
    assert report["checks"]["independent_judge"]
    assert report["checks"]["human_acceptability"]


@pytest.mark.parametrize("mutation", ["missing_human", "tampered_candidate"])
def test_external_labels_reject_partial_or_mismatched_artifacts(mutation: str) -> None:
    candidate, labels, key = _artifacts()
    if mutation == "missing_human":
        labels["human_reviews"].pop()
        expected = "human_review_coverage_mismatch"
    else:
        candidate["model"] = "tampered-after-labeling"
        expected = "candidate_report_hash_mismatch"

    with pytest.raises(ValueError, match=expected):
        merge_external_labels(FIXTURE_PATH, candidate, labels, key)
