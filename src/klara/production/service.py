"""Role checks and safe audit projection for the production repository."""

from __future__ import annotations

from typing import Any

from klara.production.auth import Principal
from klara.production.exporter import TrajectoryExportService
from klara.production.repository import ProductionRepository


class ProductionRuntimeService:
    """Coordinate authenticated sessions, queue workers, outbox, and exports."""

    def __init__(self, repository: ProductionRepository, exporter: TrajectoryExportService) -> None:
        self.repository = repository
        self.exporter = exporter

    def create_session(self, principal: Principal, *, title: str, request_id: str) -> dict[str, Any]:
        principal.require("owner", "operator")
        normalized = " ".join(title.split())[:120]
        if not normalized:
            raise ValueError("title_required")
        record = self.repository.create_session(principal, title=normalized)
        self._audit(principal, "session.create", "session", record["session_id"], request_id)
        return record

    def list_sessions(self, principal: Principal) -> list[dict[str, Any]]:
        principal.require("owner", "operator")
        return self.repository.list_sessions(principal)

    def enqueue_run(
        self,
        principal: Principal,
        *,
        session_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
        request_id: str,
    ) -> tuple[dict[str, Any], bool]:
        principal.require("owner", "operator")
        key = idempotency_key.strip()
        if not 8 <= len(key) <= 128:
            raise ValueError("idempotency_key_length")
        job, created = self.repository.enqueue_job(
            principal,
            session_id=session_id,
            kind="agent.run",
            payload=payload,
            idempotency_key=key,
            max_attempts=3,
        )
        self._audit(principal, "job.enqueue" if created else "job.reuse", "job", job["job_id"], request_id)
        return job, created

    def list_jobs(self, principal: Principal) -> list[dict[str, Any]]:
        principal.require("owner", "operator")
        return self.repository.list_jobs(principal)

    def cancel(self, principal: Principal, *, job_id: str, request_id: str) -> dict[str, Any] | None:
        principal.require("owner", "operator")
        job = self.repository.cancel(principal, job_id)
        if job:
            self._audit(principal, "job.cancel", "job", job_id, request_id)
        return job

    def claim(self, principal: Principal, *, lease_seconds: int, request_id: str) -> dict[str, Any] | None:
        principal.require("worker")
        _validate_lease_seconds(lease_seconds)
        job = self.repository.claim_next(principal, lease_seconds=lease_seconds)
        if job:
            self._audit(principal, "job.claim", "job", job["job_id"], request_id)
        return job

    def heartbeat(
        self,
        principal: Principal,
        *,
        job_id: str,
        lease_token: str,
        lease_seconds: int,
        request_id: str,
    ) -> dict[str, Any]:
        principal.require("worker")
        _validate_lease_seconds(lease_seconds)
        job = self.repository.heartbeat(
            principal, job_id=job_id, lease_token=lease_token, lease_seconds=lease_seconds
        )
        self._audit(principal, "job.heartbeat", "job", job_id, request_id)
        return job

    def complete(
        self,
        principal: Principal,
        *,
        job_id: str,
        lease_token: str,
        result: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        principal.require("worker")
        job = self.repository.complete(
            principal, job_id=job_id, lease_token=lease_token, result=result
        )
        self._audit(principal, "job.complete", "job", job_id, request_id)
        return job

    def fail(
        self,
        principal: Principal,
        *,
        job_id: str,
        lease_token: str,
        error_code: str,
        retry_delay_seconds: int,
        request_id: str,
    ) -> dict[str, Any]:
        principal.require("worker")
        if not error_code or len(error_code) > 80:
            raise ValueError("invalid_error_code")
        if not 0 <= retry_delay_seconds <= 3600:
            raise ValueError("invalid_retry_delay")
        job = self.repository.fail(
            principal,
            job_id=job_id,
            lease_token=lease_token,
            error_code=error_code,
            retry_delay_seconds=retry_delay_seconds,
        )
        self._audit(principal, "job.fail", "job", job_id, request_id)
        return job

    def claim_outbox(self, principal: Principal, *, lease_seconds: int, request_id: str) -> dict[str, Any] | None:
        principal.require("worker")
        _validate_lease_seconds(lease_seconds)
        event = self.repository.claim_outbox(principal, lease_seconds=lease_seconds)
        if event:
            self._audit(principal, "outbox.claim", "outbox", event["event_id"], request_id)
        return event

    def acknowledge_outbox(
        self,
        principal: Principal,
        *,
        event_id: str,
        delivery_token: str,
        request_id: str,
    ) -> dict[str, Any]:
        principal.require("worker")
        event = self.repository.acknowledge_outbox(
            principal, event_id=event_id, delivery_token=delivery_token
        )
        self._audit(principal, "outbox.acknowledge", "outbox", event_id, request_id)
        return event

    def export_trajectory(
        self,
        principal: Principal,
        *,
        job_id: str,
        trace_path: str,
        request_id: str,
    ) -> dict[str, Any]:
        principal.require("owner", "evaluator")
        manifest = self.exporter.export_job(principal, job_id=job_id, trace_path=trace_path)
        self._audit(principal, "trajectory.export", "job", job_id, request_id)
        return manifest

    def get_job(self, principal: Principal, *, job_id: str) -> dict[str, Any] | None:
        """Return one owner-scoped job without its private payload or worker lease."""

        principal.require("owner", "operator")
        return self.repository.get_job(principal, job_id)

    def list_job_events(self, principal: Principal, *, job_id: str) -> list[dict[str, Any]] | None:
        """Return public lifecycle events for one owner-visible job."""

        principal.require("owner", "operator")
        return self.repository.list_job_events(principal, job_id)

    def _audit(
        self,
        principal: Principal,
        action: str,
        target_type: str,
        target_id: str,
        request_id: str,
    ) -> None:
        self.repository.audit(
            principal,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
        )


def _validate_lease_seconds(value: int) -> None:
    if not 15 <= value <= 900:
        raise ValueError("lease_seconds_out_of_range")
