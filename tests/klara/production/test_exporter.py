from __future__ import annotations

import json
from pathlib import Path

import pytest

from klara.eval.trajectory import load_jsonl
from klara.production import Principal, ProductionRepository, TrajectoryExportService


def test_authorized_export_is_hash_linked_and_redacted(tmp_path: Path) -> None:
    repository = ProductionRepository(tmp_path / "production.sqlite3")
    owner = Principal("tenant-a", "alice", frozenset({"owner", "evaluator"}), "token", 2_000_000_000)
    other = Principal("tenant-a", "bob", frozenset({"owner", "evaluator"}), "token", 2_000_000_000)
    session = repository.create_session(owner, title="Export")
    job, _ = repository.enqueue_job(
        owner,
        session_id=session["session_id"],
        kind="agent.run",
        payload={"question": "private user prompt"},
        idempotency_key="request-export",
        max_attempts=3,
    )
    trace_root = tmp_path / "traces"
    trace_root.mkdir()
    trace = trace_root / "runs.jsonl"
    events = [
        _event(job["run_id"], 1, "run.started", {}),
        _event(job["run_id"], 2, "turn.started", {"turn_index": 1}),
        _event(job["run_id"], 3, "tool.started", {"tool_call": {"id": "call-1", "name": "web_fetch", "arguments": {"private": "drop"}}}),
        _event(job["run_id"], 4, "tool.completed", {"tool_result": {"tool_call_id": "call-1", "name": "web_fetch", "content": "drop"}}),
        _event(job["run_id"], 5, "run.completed", {"metrics": {"duration_ms": 12, "total_tokens": 9}, "final_answer": "drop"}),
    ]
    trace.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    exporter = TrajectoryExportService(repository, tmp_path / "exports", allowed_trace_roots=(trace_root,))

    with pytest.raises(KeyError, match="job_not_found"):
        exporter.export_job(other, job_id=job["job_id"], trace_path=trace)
    manifest = exporter.export_job(owner, job_id=job["job_id"], trace_path=trace)
    dataset = tmp_path / "exports" / manifest["dataset"]["relative_path"]
    records = load_jsonl(dataset)
    assert len(records) == 1
    assert len(records[0].events) == 5
    assert records[0].events[2].action == "web_fetch"
    serialized = dataset.read_text(encoding="utf-8")
    assert "private user prompt" not in serialized
    assert '"arguments"' not in serialized
    assert '"content"' not in serialized
    assert '"final_answer"' not in serialized
    assert manifest["privacy"]["leakage_findings"] == []

    outside = tmp_path / "outside.jsonl"
    outside.write_text(trace.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(PermissionError, match="outside_allowed"):
        exporter.export_job(owner, job_id=job["job_id"], trace_path=outside)


def _event(run_id: str, seq: int, kind: str, payload: dict) -> dict:
    return {
        "schema_version": 1,
        "event_id": f"evt-{seq}",
        "seq": seq,
        "type": kind,
        "run_id": run_id,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "payload": payload,
    }
