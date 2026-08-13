"""Authorized conversion of public run traces into redacted training records."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from klara.eval.trajectory import (
    TRAJECTORY_SCHEMA_VERSION,
    canonical_json,
    export_jsonl,
    leakage_findings,
    project_public_events,
    stable_sha256,
)
from klara.production.auth import Principal


class ExportRepository(Protocol):
    """Minimal owner-aware persistence contract needed by the exporter."""

    def get_job(
        self,
        principal: Principal,
        job_id: str,
        *,
        tenant_worker: bool = False,
    ) -> dict[str, Any] | None: ...

    def record_export(
        self,
        principal: Principal,
        *,
        export_id: str,
        job_id: str,
        dataset_path: str,
        dataset_sha256: str,
        manifest_sha256: str,
    ) -> None: ...


class TrajectoryExportService:
    """Export only runs the authenticated owner can prove it owns."""

    def __init__(
        self,
        repository: ExportRepository,
        output_root: str | Path,
        *,
        allowed_trace_roots: tuple[str | Path, ...] = ("data/traces",),
    ) -> None:
        self.repository = repository
        self.output_root = Path(output_root)
        self.allowed_trace_roots = tuple(Path(root).resolve() for root in allowed_trace_roots)

    def export_job(
        self,
        principal: Principal,
        *,
        job_id: str,
        trace_path: str | Path,
    ) -> dict[str, Any]:
        """Project one authorized run and emit a hash-linked dataset manifest."""

        job = self.repository.get_job(principal, job_id)
        if job is None:
            raise KeyError("job_not_found")
        source_path = Path(trace_path).resolve()
        if not any(source_path.is_relative_to(root) for root in self.allowed_trace_roots):
            raise PermissionError("trace_path_outside_allowed_roots")
        if not source_path.is_file():
            raise FileNotFoundError("trace_not_found")
        raw_bytes = source_path.read_bytes()
        matching: list[dict[str, Any]] = []
        for line_number, line in enumerate(raw_bytes.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid trace line {line_number}") from exc
            if isinstance(raw, dict) and raw.get("run_id") == job["run_id"]:
                matching.append(raw)
        if not matching:
            raise ValueError("authorized run has no public trace events")
        matching.sort(key=lambda item: int(item.get("seq") or 0))
        split = _split_for(job["run_id"])
        lineage_id = stable_sha256(
            canonical_json(
                {
                    "source_kind": "production_job",
                    "job_id": job["job_id"],
                    "run_id": job["run_id"],
                    "payload_sha256": job["payload_sha256"],
                }
            )
        )
        record = project_public_events(matching, split=split, lineage_id=lineage_id)
        findings = leakage_findings(record.to_dict())
        if findings:
            raise ValueError("projected trajectory failed privacy gate")

        export_id = f"exp_{uuid4().hex}"
        tenant_partition = stable_sha256(principal.tenant_id)[:16]
        directory = self.output_root / tenant_partition / export_id
        dataset_path = directory / "trajectories.jsonl"
        manifest_path = directory / "manifest.json"
        dataset_sha256 = export_jsonl((record,), dataset_path)
        manifest = {
            "schema_version": "klara.trajectory-export-manifest.v1",
            "trajectory_schema_version": TRAJECTORY_SCHEMA_VERSION,
            "export_id": export_id,
            "created_at": datetime.now(UTC).isoformat(),
            "source": {
                "kind": "production_job_public_trace",
                "job_id": job["job_id"],
                "run_id": job["run_id"],
                "trace_sha256": stable_sha256(raw_bytes),
                "payload_sha256": job["payload_sha256"],
            },
            "dataset": {
                "relative_path": f"{tenant_partition}/{export_id}/trajectories.jsonl",
                "sha256": dataset_sha256,
                "records": 1,
                "events": len(record.events),
                "split_counts": {split: 1},
                "lineage_sha256": lineage_id,
            },
            "privacy": {
                "projection": "public_lifecycle_identity_outcome_numeric_metrics_only",
                "raw_prompt_exported": False,
                "raw_tool_arguments_exported": False,
                "raw_tool_results_exported": False,
                "hidden_reasoning_exported": False,
                "leakage_findings": [],
            },
        }
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        manifest_path.write_text(manifest_text, encoding="utf-8", newline="\n")
        manifest_sha256 = stable_sha256(manifest_text)
        self.repository.record_export(
            principal,
            export_id=export_id,
            job_id=job_id,
            dataset_path=manifest["dataset"]["relative_path"],
            dataset_sha256=dataset_sha256,
            manifest_sha256=manifest_sha256,
        )
        return {
            **manifest,
            "manifest_sha256": manifest_sha256,
        }


def _split_for(run_id: str) -> str:
    bucket = int(stable_sha256(run_id)[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "validation"
    return "test"
