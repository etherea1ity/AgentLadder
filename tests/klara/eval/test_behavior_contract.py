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
    build_human_review_key,
    build_human_review_queue,
    load_fixture,
    score_observation,
    wilson_interval,
    _fact_present,
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


def test_answer_fact_groups_and_required_order_are_enforced() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"][0]
    payload["schema_version"] = "klara.behavior-case.v2"
    payload["acceptable_answer_fact_groups"] = [["needle", "针"]]
    case = KlaraBehaviorCase.model_validate(payload)
    observation = BehaviorObservation(
        case_id=case.case_id,
        repetition=1,
        final_answer="unrelated",
        actions=[],
        states=case.expected_states,
        invariant_results={item: True for item in case.invariants},
        latency_ms=1,
        tokens=1,
        cost_usd=0,
    )

    score = score_observation(case, observation)

    assert score.checks["acceptable_facts_present"] is False
    assert score.task_success is False


def test_chinese_fact_match_allows_short_natural_modifier() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"][0]
    payload["schema_version"] = "klara.behavior-case.v2"
    payload["acceptable_answer_fact_groups"] = [["避免重复计算"]]
    case = KlaraBehaviorCase.model_validate(payload)
    observation = BehaviorObservation(
        case_id=case.case_id,
        repetition=1,
        final_answer="缓存可以避免每一步都重复计算历史 token。",
        actions=list(case.reference.actions),
        states=case.expected_states,
        invariant_results={item: True for item in case.invariants},
        latency_ms=1,
        tokens=1,
        cost_usd=0,
    )

    score = score_observation(case, observation)

    assert score.checks["acceptable_facts_present"] is True


def test_prohibited_claim_match_allows_explicit_negation() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"][0]
    payload["schema_version"] = "klara.behavior-case.v2"
    payload["prohibited_claims"] = ["task was created"]
    case = KlaraBehaviorCase.model_validate(payload)
    observation = BehaviorObservation(
        case_id=case.case_id,
        repetition=1,
        final_answer="No task was created because approval is required.",
        actions=list(case.reference.actions),
        states=case.expected_states,
        invariant_results={item: True for item in case.invariants},
        latency_ms=1,
        tokens=1,
        cost_usd=0,
    )

    score = score_observation(case, observation)

    assert score.checks["prohibited_claims_absent"] is True


def test_fact_matcher_accepts_kv_connector_and_recompute_paraphrase() -> None:
    answer = "KV Cache 缓存已计算过的 Key 和 Value，从而避免每个新 token 都重算历史。"

    assert _fact_present(answer, "key/value")
    assert _fact_present(answer, "避免重复计算")
    assert _fact_present("避免每次都重新计算历史 token", "避免重复计算")
    assert _fact_present("后续生成无需重复计算全部历史", "避免重复计算")


def test_human_queue_does_not_reveal_candidate_slot() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    case = fixture.cases[0]
    observation = BehaviorObservation(
        case_id=case.case_id,
        repetition=1,
        final_answer="candidate",
        states=case.expected_states,
        invariant_results={item: True for item in case.invariants},
        latency_ms=1,
        tokens=1,
        cost_usd=0,
    )

    queue = build_human_review_queue(fixture, [observation])
    key = build_human_review_key(fixture, [observation])

    assert "candidate_slot" not in queue[0]
    assert key[queue[0]["pair_id"]] in {"a", "b"}


def test_repeated_identical_answers_receive_unique_blind_pair_ids() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    case = fixture.cases[0]
    observations = [
        BehaviorObservation(
            case_id=case.case_id,
            repetition=repetition,
            final_answer="same answer",
            states=case.expected_states,
            invariant_results={item: True for item in case.invariants},
            latency_ms=1,
            tokens=1,
            cost_usd=0,
        )
        for repetition in (1, 2)
    ]

    queue = build_human_review_queue(fixture, observations)

    assert len({item["pair_id"] for item in queue}) == 2
