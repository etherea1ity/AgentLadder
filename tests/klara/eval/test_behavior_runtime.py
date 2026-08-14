"""Real-Harness calibration tests for the frozen KlaraBench v2 cases."""

from __future__ import annotations

from pathlib import Path

from klara.eval.behavior import load_fixture, score_observation
from klara.eval.behavior_runtime import (
    CALIBRATION_KIND,
    _approval_status_only,
    _contains_clarification,
    run_live_candidate_evaluation,
    run_scripted_reference_calibration,
    run_scripted_reference_case,
)


ROOT = Path(__file__).parents[3]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "behavior" / "agent_behavior_cases.v2.json"


def test_scripted_reference_calibration_runs_all_observations_through_harness() -> None:
    report = run_scripted_reference_calibration(FIXTURE_PATH, repository_root=ROOT)

    assert report["passed"]
    assert report["gate_kind"] == CALIBRATION_KIND
    assert report["counts"] == {
        "cases": 11,
        "observations": 41,
        "critical_observations": 20,
    }
    assert "not a score" in report["interpretation"]
    assert all(run["lifecycle_event_count"] > 0 for run in report["runs"])
    assert all(run["observation"]["judge_outcome"] == "unscored" for run in report["runs"])
    assert all(run["observation"]["human_acceptable"] is None for run in report["runs"])
    assert all("action_calls" in run for run in report["runs"])
    assert all("public_tool_observations" in run for run in report["runs"])


def test_approval_status_rejects_retry_invitation() -> None:
    assert _approval_status_only(
        "The action did not happen because explicit approval is required."
    )
    assert not _approval_status_only(
        "The action was blocked; if you'd like, confirm approval and I'll retry."
    )


def test_natural_which_word_counts_as_clarification() -> None:
    assert _contains_clarification("需要知道哪个文件，以及哪个位置。")


def test_task_create_reference_is_blocked_by_real_permission_engine(tmp_path) -> None:
    fixture = load_fixture(FIXTURE_PATH)
    case = next(item for item in fixture.cases if item.case_id == "hidden-task-create-approval-001")

    result = run_scripted_reference_case(
        case,
        repetition=1,
        repository_root=ROOT,
        scratch_root=tmp_path,
    )
    score = score_observation(case, result.observation)

    assert score.task_success
    assert result.executed_actions == ()
    assert result.blocked_actions == ("task_create",)
    assert "approval_required" in result.observation.states
    assert "stopped_without_mutation" in result.observation.states


def test_live_candidate_refuses_zero_paid_api_budget() -> None:
    manifest = ROOT / "config" / "stages" / "agent-product-benchmarks.manifest.json"

    try:
        run_live_candidate_evaluation(
            FIXTURE_PATH,
            manifest,
            repository_root=ROOT,
            input_cost_per_million=1,
            output_cost_per_million=1,
        )
    except ValueError as exc:
        assert str(exc) == "paid_api_budget_not_authorized"
    else:  # pragma: no cover - protects the no-spend contract
        raise AssertionError("zero-budget manifest unexpectedly called the candidate")


def test_live_candidate_rejects_unknown_case_selection_before_api() -> None:
    manifest = ROOT / "config" / "stages" / "agent-product-benchmarks.manifest.json"

    try:
        run_live_candidate_evaluation(
            FIXTURE_PATH,
            manifest,
            repository_root=ROOT,
            input_cost_per_million=1,
            output_cost_per_million=1,
            case_ids=("missing-case",),
        )
    except ValueError as exc:
        assert str(exc) == "candidate_case_selection_unknown:missing-case"
    else:  # pragma: no cover
        raise AssertionError("unknown case selection unexpectedly reached the API")
