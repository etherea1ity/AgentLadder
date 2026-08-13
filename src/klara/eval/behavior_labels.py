"""Strictly merge independently produced labels into a live behavior run."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from klara.eval.behavior import (
    BehaviorObservation,
    build_human_review_key,
    build_human_review_queue,
    load_fixture,
    score_observation,
    stable_hash,
)
from klara.eval.behavior_report import build_behavior_report


LABEL_SCHEMA_VERSION = "klara.behavior-external-labels.v1"
LABEL_MERGER_VERSION = "klara.behavior-label-merger.v1"
_JUDGE_OUTCOMES = {"better", "equivalent", "worse", "invalid"}


def merge_external_labels(
    fixture_path: Path,
    candidate_report: dict[str, Any],
    labels: dict[str, Any],
    private_review_key: dict[str, str],
) -> dict[str, Any]:
    """Return a rescored report only when every external label has exact coverage."""

    fixture = load_fixture(fixture_path)
    fixture_sha256 = stable_hash(json.loads(fixture_path.read_text(encoding="utf-8")))
    if candidate_report.get("fixture_sha256") != fixture_sha256:
        raise ValueError("candidate_fixture_hash_mismatch")
    if labels.get("schema_version") != LABEL_SCHEMA_VERSION:
        raise ValueError("unsupported_external_label_schema")
    if labels.get("candidate_report_sha256") != stable_hash(candidate_report):
        raise ValueError("candidate_report_hash_mismatch")
    _require_provenance(labels)

    raw_observations = candidate_report.get("observations")
    if not isinstance(raw_observations, list):
        raise ValueError("candidate_observations_missing")
    observations = [BehaviorObservation.model_validate(item) for item in raw_observations]
    if any(
        item.reference_success is not None
        or item.judge_outcome != "unscored"
        or item.human_acceptable is not None
        for item in observations
    ):
        raise ValueError("candidate_report_contains_prefilled_external_labels")
    expected = {
        (case.case_id, repetition)
        for case in fixture.cases
        for repetition in range(1, case.repetitions + 1)
    }
    observed = [(item.case_id, item.repetition) for item in observations]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        raise ValueError("candidate_observation_coverage_mismatch")

    references = _indexed_rows(labels.get("reference_results"), expected, "reference")
    judges = _indexed_rows(labels.get("judge_results"), expected, "judge")
    runtime_contracts = _runtime_contracts(candidate_report.get("runtime_runs"), expected)
    for key, row in references.items():
        if row.get("comparison_contract_sha256") != runtime_contracts[key]:
            raise ValueError("reference_comparison_contract_mismatch")
        _require_sha256(row.get("run_artifact_sha256"), "reference_run_artifact_sha256")
    for row in judges.values():
        if row.get("outcome") not in _JUDGE_OUTCOMES:
            raise ValueError("invalid_judge_outcome")
        _require_sha256(row.get("judge_artifact_sha256"), "judge_artifact_sha256")

    expected_key = build_human_review_key(fixture, observations)
    if private_review_key != expected_key:
        raise ValueError("private_review_key_mismatch")
    reviews = labels.get("human_reviews")
    if not isinstance(reviews, list):
        raise ValueError("human_reviews_missing")
    review_by_pair: dict[str, dict[str, Any]] = {}
    for row in reviews:
        if not isinstance(row, dict) or not isinstance(row.get("pair_id"), str):
            raise ValueError("invalid_human_review_row")
        pair_id = row["pair_id"]
        if pair_id in review_by_pair:
            raise ValueError("duplicate_human_review")
        if not isinstance(row.get("answer_a_acceptable"), bool) or not isinstance(
            row.get("answer_b_acceptable"), bool
        ):
            raise ValueError("human_review_requires_blind_boolean_ratings")
        review_by_pair[pair_id] = row
    if set(review_by_pair) != set(expected_key):
        raise ValueError("human_review_coverage_mismatch")

    queue = build_human_review_queue(fixture, observations)
    pair_by_case = {
        (item.case_id, item.repetition): queue_item["pair_id"]
        for item, queue_item in zip(
            sorted(observations, key=lambda value: (value.case_id, value.repetition)),
            queue,
            strict=True,
        )
    }
    merged: list[BehaviorObservation] = []
    for observation in observations:
        key = (observation.case_id, observation.repetition)
        pair_id = pair_by_case[key]
        candidate_slot = private_review_key[pair_id]
        review = review_by_pair[pair_id]
        payload = observation.model_dump(mode="json")
        payload.update(
            {
                "reference_success": references[key].get("task_success"),
                "judge_outcome": judges[key]["outcome"],
                "human_acceptable": review[f"answer_{candidate_slot}_acceptable"],
            }
        )
        if not isinstance(payload["reference_success"], bool):
            raise ValueError("reference_result_requires_boolean_task_success")
        merged.append(BehaviorObservation.model_validate(payload))

    cases = {case.case_id: case for case in fixture.cases}
    thresholds = candidate_report.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("candidate_thresholds_missing")
    report = build_behavior_report(
        fixture,
        [score_observation(cases[item.case_id], item) for item in merged],
        thresholds=thresholds,
        fixture_sha256=fixture_sha256,
    )
    preserved = {
        key: deepcopy(candidate_report[key])
        for key in (
            "runner_version",
            "model",
            "declared_paid_api_budget_usd",
            "estimated_cost_usd",
            "pricing",
            "runtime_runs",
        )
        if key in candidate_report
    }
    report.update(preserved)
    report.update(
        {
            "gate_kind": "live_candidate_evaluation_with_external_labels",
            "label_merger_version": LABEL_MERGER_VERSION,
            "candidate_report_sha256": stable_hash(candidate_report),
            "label_artifact_sha256": stable_hash(labels),
            "external_label_provenance": deepcopy(labels["provenance"]),
            "thresholds": deepcopy(thresholds),
            "observations": [item.model_dump(mode="json") for item in merged],
            "interpretation": (
                "The real-Harness candidate run was rescored after exact-coverage "
                "live-reference, independent-judge, and blind-human labels were "
                "validated and merged without exposing the private answer key."
            ),
        }
    )
    return report


def _indexed_rows(
    value: Any, expected: set[tuple[str, int]], label: str
) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label}_results_missing")
    indexed: dict[tuple[str, int], dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict):
            raise ValueError(f"invalid_{label}_result")
        try:
            key = (str(row["case_id"]), int(row["repetition"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid_{label}_result") from exc
        if key in indexed:
            raise ValueError(f"duplicate_{label}_result")
        indexed[key] = row
    if set(indexed) != expected:
        raise ValueError(f"{label}_result_coverage_mismatch")
    return indexed


def _require_provenance(labels: dict[str, Any]) -> None:
    provenance = labels.get("provenance")
    required = {"reference", "judge", "human"}
    if not isinstance(provenance, dict) or set(provenance) != required:
        raise ValueError("external_label_provenance_missing")
    if any(not isinstance(provenance[name], str) or not provenance[name].strip() for name in required):
        raise ValueError("external_label_provenance_missing")


def _runtime_contracts(
    value: Any, expected: set[tuple[str, int]]
) -> dict[tuple[str, int], str]:
    rows = _indexed_rows(value, expected, "candidate_runtime")
    contracts: dict[tuple[str, int], str] = {}
    for key, row in rows.items():
        contract = row.get("comparison_contract_sha256")
        _require_sha256(contract, "candidate_comparison_contract_sha256")
        contracts[key] = contract
    return contracts


def _require_sha256(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"invalid_{field}")
