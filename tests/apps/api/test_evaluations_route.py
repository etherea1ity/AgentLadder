"""API tests for the aggregate evaluation surface."""

from __future__ import annotations

from apps.api.main import app
from apps.api.routes.evaluations import get_evaluation_summary


def test_evaluation_summary_is_aggregate_and_read_only() -> None:
    assert "/api/evaluations/summary" in {route.path for route in app.routes}

    payload = get_evaluation_summary()
    assert set(payload) == {
        "available",
        "status",
        "gate_kind",
        "interpretation",
        "scorer_version",
        "evaluated_at",
        "counts",
        "metrics",
        "checks",
        "split_hashes",
    }
    assert "case_scores" not in payload
