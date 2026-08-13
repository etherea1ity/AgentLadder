"""Versioned behavior cases, observations, deterministic scoring, and review queues."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import sqrt
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

from pydantic import BaseModel, Field, model_validator


CASE_SCHEMA_VERSION = "klara.behavior-case.v1"
CASE_SCHEMA_VERSIONS = frozenset({CASE_SCHEMA_VERSION, "klara.behavior-case.v2"})
FIXTURE_SCHEMA_VERSION = "klara.behavior-fixture.v1"
FIXTURE_SCHEMA_VERSIONS = frozenset(
    {FIXTURE_SCHEMA_VERSION, "klara.behavior-fixture.v2"}
)
SCORER_VERSION = "klara.behavior-scorer.v2"

BehaviorSplit = Literal[
    "development", "validation", "hidden_regression", "adversarial"
]
BehaviorLanguage = Literal["zh", "en", "mixed"]
BehaviorRisk = Literal["low", "medium", "high", "critical"]
ReviewOutcome = Literal["better", "equivalent", "worse", "invalid", "unscored"]


class BehaviorMessage(BaseModel):
    """One public message supplied as behavior-case context."""

    role: Literal["user", "assistant", "tool"]
    content: str = Field(min_length=1)


class BehaviorLimits(BaseModel):
    """Per-case execution ceilings frozen before a candidate run."""

    maximum_steps: int = Field(ge=1)
    maximum_tokens: int = Field(ge=1)
    maximum_cost_usd: float = Field(ge=0)
    maximum_latency_ms: int = Field(ge=1)


class BehaviorReference(BaseModel):
    """Public reference answer and action path; never hidden reasoning."""

    answer: str = Field(min_length=1)
    actions: list[str] = Field(default_factory=list)
    action_arguments: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_actions(self) -> "BehaviorReference":
        if self.action_arguments and len(self.action_arguments) != len(self.actions):
            raise ValueError("reference action arguments must align with actions")
        return self


class KlaraBehaviorCase(BaseModel):
    """One frozen user-habit case with explicit state and action constraints."""

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    schema_version: str
    source: str = Field(min_length=1)
    license: str = Field(min_length=1)
    split: BehaviorSplit
    scenario_family: str = Field(min_length=1)
    language: BehaviorLanguage
    risk: BehaviorRisk
    capability_tags: list[str] = Field(min_length=1)
    initial_messages: list[BehaviorMessage] = Field(default_factory=list)
    user_turn: str = Field(min_length=1)
    environment: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    must_call: list[str] = Field(default_factory=list)
    may_call: list[str] = Field(default_factory=list)
    must_not_call: list[str] = Field(default_factory=list)
    expected_states: list[str] = Field(min_length=1)
    invariants: list[str] = Field(min_length=1)
    acceptable_answer_facts: list[str] = Field(default_factory=list)
    acceptable_answer_fact_groups: list[list[str]] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    must_call_in_order: list[str] = Field(default_factory=list)
    limits: BehaviorLimits
    repetitions: int = Field(ge=1)
    critical: bool = False
    reference: BehaviorReference

    @model_validator(mode="after")
    def validate_contract(self) -> "KlaraBehaviorCase":
        """Reject schema drift and contradictory action requirements."""

        if self.schema_version not in CASE_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported behavior case schema: {self.schema_version}")
        must = set(self.must_call)
        may = set(self.may_call)
        forbidden = set(self.must_not_call)
        if must & forbidden or may & forbidden:
            raise ValueError("allowed and forbidden action sets must be disjoint")
        if self.must_call_in_order and not set(self.must_call_in_order).issubset(must):
            raise ValueError("ordered calls must also be required calls")
        if any(not group or any(not item.strip() for item in group) for group in self.acceptable_answer_fact_groups):
            raise ValueError("answer fact groups must contain non-empty alternatives")
        if self.critical and self.repetitions < 5:
            raise ValueError("critical behavior cases require at least five repetitions")
        return self


class BehaviorFixture(BaseModel):
    """One licensed collection whose scenario families cannot cross splits."""

    schema_version: str
    license: str = Field(min_length=1)
    cases: list[KlaraBehaviorCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fixture(self) -> "BehaviorFixture":
        """Enforce stable IDs and scenario-family split isolation."""

        if self.schema_version not in FIXTURE_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported behavior fixture schema: {self.schema_version}")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("behavior case ids must be unique")
        family_splits: dict[str, set[str]] = {}
        # Families, rather than wording variants, define contamination boundaries.
        for case in self.cases:
            family_splits.setdefault(case.scenario_family, set()).add(case.split)
        leaked = sorted(family for family, splits in family_splits.items() if len(splits) > 1)
        if leaked:
            raise ValueError(f"scenario families cross splits: {leaked}")
        return self

    def split_hashes(self) -> dict[str, str]:
        """Return deterministic SHA-256 hashes for every frozen split."""

        hashes: dict[str, str] = {}
        for split in ("development", "validation", "hidden_regression", "adversarial"):
            records = [
                case.model_dump(mode="json")
                for case in sorted(self.cases, key=lambda item: item.case_id)
                if case.split == split
            ]
            hashes[split] = stable_hash(records)
        return hashes


class BehaviorObservation(BaseModel):
    """Public candidate outcome supplied to deterministic and review graders."""

    case_id: str
    repetition: int = Field(ge=1)
    final_answer: str = ""
    actions: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    invariant_results: dict[str, bool] = Field(default_factory=dict)
    latency_ms: int = Field(ge=0)
    tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    reference_success: bool | None = None
    judge_outcome: ReviewOutcome = "unscored"
    human_acceptable: bool | None = None
    p0_failures: list[str] = Field(default_factory=list)
    p1_failures: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class BehaviorCaseScore:
    """Deterministic score for one case repetition."""

    case_id: str
    repetition: int
    split: str
    language: str
    critical: bool
    capability_tags: tuple[str, ...]
    checks: dict[str, bool]
    task_success: bool
    reference_success: bool | None
    judge_outcome: ReviewOutcome
    human_acceptable: bool | None
    p0_count: int
    p1_count: int
    latency_ms: int
    tokens: int
    cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize the immutable score."""

        return {
            "case_id": self.case_id,
            "repetition": self.repetition,
            "split": self.split,
            "language": self.language,
            "critical": self.critical,
            "capability_tags": list(self.capability_tags),
            "checks": self.checks,
            "task_success": self.task_success,
            "reference_success": self.reference_success,
            "judge_outcome": self.judge_outcome,
            "human_acceptable": self.human_acceptable,
            "p0_count": self.p0_count,
            "p1_count": self.p1_count,
            "latency_ms": self.latency_ms,
            "tokens": self.tokens,
            "cost_usd": self.cost_usd,
        }


class BehaviorJudge(Protocol):
    """Adapter boundary for an independent public-answer judge."""

    def grade(self, *, case: KlaraBehaviorCase, candidate: str, reference: str) -> ReviewOutcome:
        """Return an anonymous pairwise outcome without hidden reasoning."""


def load_fixture(path: Path) -> BehaviorFixture:
    """Load and validate one behavior fixture from JSON."""

    return BehaviorFixture.model_validate_json(path.read_text(encoding="utf-8"))


def stable_hash(value: Any) -> str:
    """Hash one JSON-compatible object with stable Unicode serialization."""

    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def score_observation(
    case: KlaraBehaviorCase, observation: BehaviorObservation
) -> BehaviorCaseScore:
    """Evaluate exact state, action, artifact, budget, and claim invariants."""

    if observation.case_id != case.case_id:
        raise ValueError("observation case id does not match behavior case")
    action_set = set(observation.actions)
    state_set = set(observation.states)
    artifact_set = set(observation.artifacts)
    normalized_answer = " ".join(observation.final_answer.lower().split())
    missing_invariants = [
        invariant
        for invariant in case.invariants
        if invariant not in observation.invariant_results
    ]
    if missing_invariants:
        raise ValueError(f"missing invariant grades: {missing_invariants}")
    checks = {
        "answer_present": bool(observation.final_answer.strip()),
        "must_calls_present": set(case.must_call).issubset(action_set),
        "forbidden_calls_absent": not set(case.must_not_call) & action_set,
        "expected_states_present": set(case.expected_states).issubset(state_set),
        "expected_artifacts_present": set(case.expected_artifacts).issubset(artifact_set),
        "invariants_pass": all(observation.invariant_results[item] for item in case.invariants),
        "prohibited_claims_absent": not any(
            claim.lower() in normalized_answer for claim in case.prohibited_claims
        ),
        "acceptable_facts_present": all(
            any(alternative.casefold() in normalized_answer for alternative in group)
            for group in case.acceptable_answer_fact_groups
        ),
        "required_call_order": _is_subsequence(
            case.must_call_in_order, observation.actions
        ),
        "step_budget": len(observation.actions) <= case.limits.maximum_steps,
        "token_budget": observation.tokens <= case.limits.maximum_tokens,
        "cost_budget": observation.cost_usd <= case.limits.maximum_cost_usd,
        "latency_budget": observation.latency_ms <= case.limits.maximum_latency_ms,
        "no_p0_failure": not observation.p0_failures,
    }
    return BehaviorCaseScore(
        case_id=case.case_id,
        repetition=observation.repetition,
        split=case.split,
        language=case.language,
        critical=case.critical,
        capability_tags=tuple(case.capability_tags),
        checks=checks,
        task_success=all(checks.values()),
        reference_success=observation.reference_success,
        judge_outcome=observation.judge_outcome,
        human_acceptable=observation.human_acceptable,
        p0_count=len(observation.p0_failures),
        p1_count=len(observation.p1_failures),
        latency_ms=observation.latency_ms,
        tokens=observation.tokens,
        cost_usd=observation.cost_usd,
    )


def wilson_interval(successes: int, total: int, *, z: float = 1.96) -> tuple[float, float]:
    """Return a Wilson score interval for a binomial rate."""

    if total < 1:
        return (0.0, 0.0)
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def anonymous_review_pair(
    case: KlaraBehaviorCase,
    candidate: str,
    *,
    repetition: int | None = None,
) -> dict[str, str]:
    """Build a stable blind A/B pair without exposing which side is candidate."""

    pair_id = stable_hash(
        {
            "case_id": case.case_id,
            "repetition": repetition,
            "candidate": candidate,
        }
    )[:20]
    candidate_first = int(pair_id[-1], 16) % 2 == 0
    return {
        "pair_id": pair_id,
        "case_id": case.case_id,
        "answer_a": candidate if candidate_first else case.reference.answer,
        "answer_b": case.reference.answer if candidate_first else candidate,
        "candidate_slot": "a" if candidate_first else "b",
    }


def build_human_review_queue(
    fixture: BehaviorFixture, observations: Sequence[BehaviorObservation]
) -> list[dict[str, str]]:
    """Return blind review pairs only for candidate outputs lacking human labels."""

    cases = {case.case_id: case for case in fixture.cases}
    queue = []
    # Preserve case/repetition order so review artifacts are reproducible.
    for observation in sorted(observations, key=lambda item: (item.case_id, item.repetition)):
        if observation.human_acceptable is None:
            pair = anonymous_review_pair(
                cases[observation.case_id],
                observation.final_answer,
                repetition=observation.repetition,
            )
            queue.append(
                {
                    key: value
                    for key, value in pair.items()
                    if key != "candidate_slot"
                }
            )
    return queue


def build_human_review_key(
    fixture: BehaviorFixture, observations: Sequence[BehaviorObservation]
) -> dict[str, str]:
    """Build the private decode key separately from the blind reviewer queue."""

    cases = {case.case_id: case for case in fixture.cases}
    return {
        pair["pair_id"]: pair["candidate_slot"]
        for observation in observations
        if observation.human_acceptable is None
        for pair in [
            anonymous_review_pair(
                cases[observation.case_id],
                observation.final_answer,
                repetition=observation.repetition,
            )
        ]
    }


def _is_subsequence(required: Sequence[str], observed: Sequence[str]) -> bool:
    if not required:
        return True
    iterator = iter(observed)
    return all(any(item == expected for item in iterator) for expected in required)
