"""Deterministic trajectory validation and algorithm evaluation."""

from klara.eval.dataset import DatasetValidation, validate_dataset
from klara.eval.report import EvaluationReport
from klara.eval.scorers import evaluate_fixture
from klara.eval.trajectory import (
    TRAJECTORY_SCHEMA_VERSION,
    TrajectoryEvent,
    TrajectoryRecord,
    canonical_json,
    export_jsonl,
    load_jsonl,
    project_public_events,
    stable_sha256,
)

__all__ = [
    "DatasetValidation",
    "EvaluationReport",
    "TRAJECTORY_SCHEMA_VERSION",
    "TrajectoryEvent",
    "TrajectoryRecord",
    "canonical_json",
    "evaluate_fixture",
    "export_jsonl",
    "load_jsonl",
    "project_public_events",
    "stable_sha256",
    "validate_dataset",
]
