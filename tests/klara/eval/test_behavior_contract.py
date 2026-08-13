"""Strict tests for the shared Agent behavior evaluation contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from klara.eval.behavior import (
    BehaviorFixture,
    BehaviorObservation,
    KlaraBehaviorCase,
    anonymous_review_pair,
    load_fixture,
    score_observation,
    wilson_interval,
)
from klara.eval.behavior_cli import run_contract_gate


ROOT = Path(__file__).parents[3]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "behavior" / "agent_behavior_cases.json"
CONFIG_PATH = ROOT / "config" / "evaluation" / "agent_behavior.toml"


def test_fixture_has_disjoint_scenario_families_and_all_required_splits() -> None:
    fixture = load_fixture(FIXTURE_PATH)

    assert {case.split for case in fixture.cases} == {
        "development",
        "validation",
        "hidden_regression",
        "adversarial",
    }
    assert len(set(fixture.split_hashes().values())) == 4


def test_fixture_rejects_scenario_family_leakage_between_splits() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["cases"][2]["scenario_family"] = payload["cases"][0]["scenario_family"]

    with pytest.raises(ValueError, match="scenario families cross splits"):
        BehaviorFixture.model_validate(payload)


def test_critical_case_requires_five_repetitions() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"][4]
    payload["repetitions"] = 4

    with pytest.raises(ValueError, match="at least five"):
        KlaraBehaviorCase.model_validate(payload)


def test_deterministic_scorer_blocks_forbidden_action_and_p0() -> None:
    case = load_fixture(FIXTURE_PATH).cases[-1]
    observation = BehaviorObservation(
        case_id=case.case_id,
        repetition=1,
        final_answer="Deletion succeeded",
        actions=["shell"],
        states=["completed"],
        artifacts=[],
        invariant_results={invariant: False for invariant in case.invariants},
        latency_ms=10,
        tokens=10,
        cost_usd=0,
        p0_failures=["unauthorized_destructive_action"],
    )

    score = score_observation(case, observation)

    assert not score.task_success
    assert not score.checks["forbidden_calls_absent"]
    assert not score.checks["no_p0_failure"]


def test_anonymous_pair_is_stable_without_using_random_state() -> None:
    case = load_fixture(FIXTURE_PATH).cases[0]

    assert anonymous_review_pair(case, "candidate") == anonymous_review_pair(
        case, "candidate"
    )


def test_wilson_interval_contains_observed_rate() -> None:
    lower, upper = wilson_interval(9, 10)

    assert lower < 0.9 < upper


def test_contract_gate_is_labeled_as_control_probe() -> None:
    report = run_contract_gate(FIXTURE_PATH, CONFIG_PATH, repository_root=ROOT)

    assert report["passed"]
    assert report["gate_kind"] == "contract_control_probe"
    assert "does not measure" in report["interpretation"]
    assert report["documentation"]["passed"]
