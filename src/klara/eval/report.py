"""Single-source JSON and Markdown evaluation reporting."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class EvaluationReport:
    """One immutable result rendered into every report format."""

    stage: str
    scorer_version: str
    evaluated_at: str
    fixture_sha256: str
    trajectory_sha256: str
    deterministic_export_sha256: str
    dataset: dict[str, Any]
    metrics: dict[str, float | int]
    counts: dict[str, int]
    operational: dict[str, float | int]
    checks: dict[str, bool]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical machine-readable report object."""

        return {
            "stage": self.stage,
            "scorer_version": self.scorer_version,
            "evaluated_at": self.evaluated_at,
            "fixture_sha256": self.fixture_sha256,
            "trajectory_sha256": self.trajectory_sha256,
            "deterministic_export_sha256": self.deterministic_export_sha256,
            "dataset": self.dataset,
            "metrics": self.metrics,
            "counts": self.counts,
            "operational": self.operational,
            "checks": self.checks,
            "passed": self.passed,
        }

    def to_json(self) -> str:
        """Render stable pretty JSON with a trailing newline."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

    def to_markdown(self) -> str:
        """Render a human-readable view from the same result fields."""

        status = "PASS" if self.passed else "FAIL"
        lines = [
            "# Lab A - Evidence And Trajectory Evaluation",
            "",
            f"Status: **{status}**",
            "",
            f"- Stage: `{self.stage}`",
            f"- Scorer: `{self.scorer_version}`",
            f"- Evaluated at: `{self.evaluated_at}`",
            f"- Fixture SHA-256: `{self.fixture_sha256}`",
            f"- Trajectory SHA-256: `{self.trajectory_sha256}`",
            f"- Deterministic export SHA-256: `{self.deterministic_export_sha256}`",
            "",
            "## Dataset Gate",
            "",
            "| Measure | Value |",
            "| --- | ---: |",
        ]
        for key in (
            "total_records",
            "valid_records",
            "schema_validation_rate",
            "linkage_checks",
            "linkage_passed",
            "id_linkage_rate",
            "leakage_finding_count",
        ):
            lines.append(f"| {key} | {_format(self.dataset[key])} |")
        lines.extend(
            [
                "",
                "## Quality Metrics",
                "",
                "| Metric | Value |",
                "| --- | ---: |",
            ]
        )
        for key, value in sorted(self.metrics.items()):
            lines.append(f"| {key} | {_format(value)} |")
        lines.extend(
            [
                "",
                "## Operational Totals",
                "",
                "| Measure | Value |",
                "| --- | ---: |",
            ]
        )
        for key, value in sorted(self.operational.items()):
            lines.append(f"| {key} | {_format(value)} |")
        lines.extend(
            [
                "",
                "## Acceptance Checks",
                "",
                "| Check | Result |",
                "| --- | --- |",
            ]
        )
        for key, value in sorted(self.checks.items()):
            lines.append(f"| {key} | {'PASS' if value else 'FAIL'} |")
        lines.extend(
            [
                "",
                "## Interpretation",
                "",
                "The fixture covers supported, contradicted, insufficient, stale, "
                "and irrelevant evidence. A required claim is released only when an "
                "admissible source has an explicit supported link and citation. "
                "Contradicted or insufficient required claims force abstention.",
                "",
                "Operational totals are fixture measurements for scorer plumbing, not "
                "provider performance claims.",
                "",
            ]
        )
        return "\n".join(lines)


def _format(value: float | int | str) -> str:
    """Format report values consistently across Markdown rows."""

    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)

