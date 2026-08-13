"""Safe summary projection for machine-backed evaluation reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH = REPOSITORY_ROOT / "docs/reports/product/agent-eval-contract.json"


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
