"""Dataset-level validation summaries for public Klara trajectories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from klara.eval.trajectory import TrajectoryRecord, leakage_findings


@dataclass(frozen=True)
class DatasetValidation:
    """Machine-readable schema, linkage, and leakage gate result."""

    total_records: int
    valid_records: int
    linkage_checks: int
    linkage_passed: int
    leakage_findings: tuple[str, ...]

    @property
    def schema_validation_rate(self) -> float:
        """Return the fraction of records accepted by the versioned schema."""

        return _ratio(self.valid_records, self.total_records)

    @property
    def id_linkage_rate(self) -> float:
        """Return the fraction of atomic join checks that passed."""

        return _ratio(self.linkage_passed, self.linkage_checks)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the dataset gate result."""

        return {
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "schema_validation_rate": self.schema_validation_rate,
            "linkage_checks": self.linkage_checks,
            "linkage_passed": self.linkage_passed,
            "id_linkage_rate": self.id_linkage_rate,
            "leakage_finding_count": len(self.leakage_findings),
            "leakage_findings": list(self.leakage_findings),
        }


def validate_dataset(records: Iterable[TrajectoryRecord]) -> DatasetValidation:
    """Revalidate records and aggregate all deterministic gate counts."""

    materialized = tuple(records)
    if not materialized:
        raise ValueError("trajectory dataset must not be empty")
    valid = 0
    linkage_passed = 0
    linkage_checks = 0
    leaks: list[str] = []
    for record in materialized:
        record.validate()
        valid += 1
        passed, total = record.linkage_counts()
        linkage_passed += passed
        linkage_checks += total
        leaks.extend(leakage_findings(record.to_dict(), f"$.{record.run_id}"))
    return DatasetValidation(
        total_records=len(materialized),
        valid_records=valid,
        linkage_checks=linkage_checks,
        linkage_passed=linkage_passed,
        leakage_findings=tuple(sorted(leaks)),
    )


def _ratio(numerator: int, denominator: int) -> float:
    """Return a stable rate while refusing vacuous all-empty gates."""

    return numerator / denominator if denominator else 0.0

