"""Safe summary projection for machine-backed evaluation reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH = REPOSITORY_ROOT / "docs/reports/product/agent-eval-contract.json"
DEFAULT_REPORT_ROOT = REPOSITORY_ROOT / "docs/reports/product"


def load_evaluation_summary(path: Path = DEFAULT_REPORT_PATH) -> dict[str, Any]:
    """Load one report and expose aggregates without hidden cases or review keys."""

    if not path.exists():
        return {
            "available": False,
            "status": "not_run",
            "gate_kind": "unknown",
            "interpretation": "No evaluation report is available yet.",
            "scorer_version": None,
            "evaluated_at": None,
            "counts": {},
            "metrics": {},
            "checks": {},
            "split_hashes": {},
        }
    report = json.loads(path.read_text(encoding="utf-8"))
    required = {"passed", "gate_kind", "interpretation", "counts", "metrics", "checks"}
    missing = sorted(required - set(report))
    if missing:
        raise ValueError(f"evaluation report missing fields: {missing}")
    return {
        "available": True,
        "status": "passed" if report["passed"] else "failed",
        "gate_kind": report["gate_kind"],
        "interpretation": report["interpretation"],
        "scorer_version": report.get("scorer_version"),
        "evaluated_at": report.get("evaluated_at"),
        "counts": report["counts"],
        "metrics": report["metrics"],
        "checks": report["checks"],
        "split_hashes": report.get("split_hashes", {}),
    }


def load_evaluation_catalog(root: Path = DEFAULT_REPORT_ROOT) -> dict[str, Any]:
    """Return safe aggregate projections for every machine-backed product gate.

    A report is included only when it declares the common gate contract.  Raw
    case scores, hidden split identifiers, reviewer queues, and free-form
    behavior examples deliberately stay on disk.
    """

    if not root.exists():
        return {"schema_version": "klara.evaluation-catalog.v1", "runs": []}
    runs: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(report, dict) or not {"passed", "gate_kind", "checks"}.issubset(report):
            continue
        checks = report.get("checks")
        metrics = report.get("metrics")
        counts = report.get("counts")
        if not isinstance(checks, dict) or not isinstance(metrics, dict):
            continue
        safe_checks = {str(key): bool(value) for key, value in checks.items() if isinstance(value, bool)}
        safe_metrics = {
            str(key): float(value)
            for key, value in metrics.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        safe_counts = {
            str(key): int(value)
            for key, value in (counts.items() if isinstance(counts, dict) else ())
            if isinstance(value, int) and not isinstance(value, bool)
        }
        runs.append(
            {
                "artifact_id": path.stem,
                "status": "passed" if report["passed"] else "failed",
                "gate_kind": str(report.get("gate_kind", "unknown"))[:120],
                "stage": str(report.get("stage", "product"))[:120],
                "interpretation": str(report.get("interpretation", ""))[:800],
                "scorer_version": _optional_text(report.get("scorer_version"), limit=120),
                "evaluated_at": _optional_text(report.get("evaluated_at"), limit=80),
                "counts": safe_counts,
                "metrics": safe_metrics,
                "checks": safe_checks,
            }
        )
    runs.sort(key=lambda item: (str(item.get("evaluated_at") or ""), str(item["artifact_id"])), reverse=True)
    return {"schema_version": "klara.evaluation-catalog.v1", "runs": runs}


def _optional_text(value: object, *, limit: int) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]
