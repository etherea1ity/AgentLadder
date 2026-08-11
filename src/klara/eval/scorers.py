"""Exact deterministic scorers for evidence-controlled agent trajectories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from klara.eval.dataset import DatasetValidation
from klara.eval.report import EvaluationReport
from klara.services.evidence import (
    AnswerFrame,
    Citation,
    Claim,
    ClaimEvidenceLink,
    EvidenceController,
    EvidencePack,
    EvidenceRecord,
)


SCORER_VERSION = "klara.evidence-eval.v1"


@dataclass(frozen=True)
class _SetCounts:
    """Aggregated true-positive, predicted, and gold set counts."""

    true_positive: int = 0
    predicted: int = 0
    gold: int = 0

    def add(self, predicted: set[str], gold: set[str]) -> "_SetCounts":
        """Return a new aggregate after one exact-set comparison."""

        return _SetCounts(
            true_positive=self.true_positive + len(predicted & gold),
            predicted=self.predicted + len(predicted),
            gold=self.gold + len(gold),
        )

    @property
    def precision(self) -> float:
        """Return micro precision; empty predictions are not a perfect score."""

        return self.true_positive / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        """Return micro recall; empty gold sets are not a vacuous score."""

        return self.true_positive / self.gold if self.gold else 0.0


def evaluate_fixture(
    fixture: dict[str, Any],
    *,
    dataset: DatasetValidation,
    fixture_sha256: str,
    trajectory_sha256: str,
    deterministic_export_sha256: str,
    deterministic_hash_match: bool,
    thresholds: dict[str, float | int],
) -> EvaluationReport:
    """Evaluate all fixture cases and return the one report source object."""

    raw_cases = fixture.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("evaluation fixture requires a non-empty cases list")

    evidence_counts = _SetCounts()
    citation_counts = _SetCounts()
    claim_correct = 0
    claim_total = 0
    contradiction_found = 0
    contradiction_total = 0
    abstention_correct = 0
    tool_correct = 0
    tool_arguments_correct = 0
    tool_total = 0
    latency_ms = 0.0
    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0
    controller = EvidenceController()

    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("evaluation case must be an object")
        case_id = _required_text(raw_case, "case_id")
        evidence = _parse_evidence_pack(raw_case.get("evidence"))
        answer = _parse_answer(raw_case.get("answer"))
        gold = raw_case.get("gold")
        if not isinstance(gold, dict):
            raise ValueError(f"case {case_id} requires a gold object")
        decision = controller.evaluate(answer, evidence)

        predicted_evidence = {f"{case_id}::{value}" for value in decision.selected_source_ids}
        gold_evidence = {
            f"{case_id}::{value}" for value in _string_list(gold, "selected_source_ids")
        }
        evidence_counts = evidence_counts.add(predicted_evidence, gold_evidence)

        predicted_citations = {f"{case_id}::{value}" for value in decision.citation_keys}
        gold_citations = {
            f"{case_id}::{value}" for value in _string_list(gold, "citation_keys")
        }
        citation_counts = citation_counts.add(predicted_citations, gold_citations)

        predicted_claims = {
            claim.claim_id: claim.judgment.value for claim in decision.claims
        }
        gold_claims = gold.get("claim_judgments")
        if not isinstance(gold_claims, dict) or not gold_claims:
            raise ValueError(f"case {case_id} requires gold claim_judgments")
        for claim_id, gold_judgment in gold_claims.items():
            claim_total += 1
            predicted = predicted_claims.get(str(claim_id))
            expected = str(gold_judgment)
            claim_correct += int(predicted == expected)
            if expected == "contradicted":
                contradiction_total += 1
                contradiction_found += int(predicted == "contradicted")

        abstention_correct += int(decision.abstained == bool(gold.get("abstained")))

        raw_tools = raw_case.get("tool_decisions", [])
        if not isinstance(raw_tools, list):
            raise ValueError(f"case {case_id} tool_decisions must be a list")
        for tool in raw_tools:
            if not isinstance(tool, dict):
                raise ValueError(f"case {case_id} tool decision must be an object")
            predicted = tool.get("predicted")
            expected = tool.get("expected")
            if not isinstance(predicted, dict) or not isinstance(expected, dict):
                raise ValueError(f"case {case_id} tool decision needs predicted/expected")
            tool_total += 1
            tool_correct += int(str(predicted.get("name")) == str(expected.get("name")))
            tool_arguments_correct += int(
                predicted.get("arguments") == expected.get("arguments")
            )

        operational = raw_case.get("operational", {})
        if not isinstance(operational, dict):
            raise ValueError(f"case {case_id} operational metrics must be an object")
        latency_ms += float(operational.get("latency_ms", 0.0))
        input_tokens += int(operational.get("input_tokens", 0))
        output_tokens += int(operational.get("output_tokens", 0))
        cost_usd += float(operational.get("cost_usd", 0.0))

    metrics: dict[str, float | int] = {
        "abstention_accuracy": _ratio(abstention_correct, len(raw_cases)),
        "citation_precision": citation_counts.precision,
        "citation_recall": citation_counts.recall,
        "claim_support_accuracy": _ratio(claim_correct, claim_total),
        "contradiction_recall": _ratio(contradiction_found, contradiction_total),
        "evidence_selection_precision": evidence_counts.precision,
        "evidence_selection_recall": evidence_counts.recall,
        "tool_argument_exactness": _ratio(tool_arguments_correct, tool_total),
        "tool_decision_accuracy": _ratio(tool_correct, tool_total),
    }
    dataset_dict = dataset.to_dict()
    checks = {
        "schema_validation": dataset.schema_validation_rate
        >= float(thresholds["schema_validation_rate"]),
        "id_linkage": dataset.id_linkage_rate
        >= float(thresholds["id_linkage_rate"]),
        "zero_secret_or_reasoning_leaks": len(dataset.leakage_findings)
        <= int(thresholds["max_leakage_findings"]),
        "deterministic_export_hash": deterministic_hash_match,
    }
    for metric_name in (
        "citation_precision",
        "citation_recall",
        "claim_support_accuracy",
        "contradiction_recall",
        "abstention_accuracy",
        "tool_decision_accuracy",
        "tool_argument_exactness",
        "evidence_selection_precision",
        "evidence_selection_recall",
    ):
        checks[metric_name] = float(metrics[metric_name]) >= float(
            thresholds[metric_name]
        )

    return EvaluationReport(
        stage=str(fixture.get("stage", "lab-a-evidence-eval")),
        scorer_version=str(fixture.get("scorer_version", SCORER_VERSION)),
        evaluated_at=str(fixture.get("evaluated_at", "")),
        fixture_sha256=fixture_sha256,
        trajectory_sha256=trajectory_sha256,
        deterministic_export_sha256=deterministic_export_sha256,
        dataset=dataset_dict,
        metrics=metrics,
        counts={
            "case_count": len(raw_cases),
            "claim_count": claim_total,
            "contradiction_count": contradiction_total,
            "tool_decision_count": tool_total,
            "selected_evidence_gold_count": evidence_counts.gold,
            "citation_gold_count": citation_counts.gold,
        },
        operational={
            "cost_usd_total": round(cost_usd, 8),
            "input_tokens_total": input_tokens,
            "latency_ms_total": round(latency_ms, 3),
            "output_tokens_total": output_tokens,
            "tokens_total": input_tokens + output_tokens,
        },
        checks=checks,
        passed=all(checks.values()),
    )


def _parse_evidence_pack(raw: Any) -> EvidencePack:
    """Parse a fixture evidence pack through production contracts."""

    if not isinstance(raw, dict) or not isinstance(raw.get("records"), list):
        raise ValueError("evidence must contain a records list")
    records = []
    for item in raw["records"]:
        if not isinstance(item, dict):
            raise ValueError("evidence record must be an object")
        records.append(
            EvidenceRecord(
                source_id=_required_text(item, "source_id"),
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                content=_required_text(item, "content"),
                fetched_at=_required_text(item, "fetched_at"),
                content_hash=str(item.get("content_hash", "")),
                status=str(item.get("status", "admissible")),
                limitations=tuple(str(value) for value in item.get("limitations", [])),
            )
        )
    return EvidencePack(records=tuple(records))


def _parse_answer(raw: Any) -> AnswerFrame:
    """Parse a fixture answer through claim/link/citation contracts."""

    if not isinstance(raw, dict):
        raise ValueError("answer must be an object")
    claims = tuple(
        Claim(
            claim_id=_required_text(item, "claim_id"),
            text=_required_text(item, "text"),
            required=bool(item.get("required", True)),
        )
        for item in _object_list(raw, "claims")
    )
    links = tuple(
        ClaimEvidenceLink(
            claim_id=_required_text(item, "claim_id"),
            source_id=_required_text(item, "source_id"),
            judgment=str(item.get("judgment", "")),
            support_note=str(item.get("support_note", "")),
        )
        for item in _object_list(raw, "links")
    )
    citations = tuple(
        Citation(
            claim_id=_required_text(item, "claim_id"),
            source_id=_required_text(item, "source_id"),
        )
        for item in _object_list(raw, "citations")
    )
    return AnswerFrame(
        claims=claims,
        links=links,
        citations=citations,
        final_text=str(raw.get("final_text", "")),
    )


def _object_list(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return one fixture list after validating every item is an object."""

    value = raw.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{key} items must be objects")
    return value


def _string_list(raw: dict[str, Any], key: str) -> list[str]:
    """Return a required list as strings."""

    value = raw.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return [str(item) for item in value]


def _required_text(raw: dict[str, Any], key: str) -> str:
    """Read one non-empty string field."""

    value = str(raw.get(key, ""))
    if not value.strip():
        raise ValueError(f"{key} must not be empty")
    return value


def _ratio(numerator: int, denominator: int) -> float:
    """Return a non-vacuous exact accuracy or recall."""

    return numerator / denominator if denominator else 0.0

