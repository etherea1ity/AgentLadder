"""One bounded worker turn over the lease-backed production queue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from klara.production.auth import Principal
from klara.production.repository import ProductionRepository, QueueLeaseError


class JobExecutor(Protocol):
    """Adapter implemented by the frozen Agent runtime or a deterministic test."""

    def __call__(self, payload: dict[str, Any], context: "WorkerContext") -> dict[str, Any]:
        """Execute one bounded payload and return public completion metadata."""


@dataclass(frozen=True)
class WorkerContext:
    """Public run identity and cooperative cancellation probe."""

    job_id: str
    run_id: str
    attempt_count: int
    _cancel_probe: Callable[[], bool]
    _heartbeat: Callable[[], None]

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_probe()

    def heartbeat(self) -> None:
        """Extend the private lease without exposing its bearer to executor code."""

        self._heartbeat()


class ProductionQueueWorker:
    """Claim, execute, and atomically complete or retry exactly one queue job."""

    def __init__(
        self,
        repository: ProductionRepository,
        principal: Principal,
        executor: JobExecutor,
        *,
        lease_seconds: int = 120,
    ) -> None:
        principal.require("worker")
        if not 15 <= lease_seconds <= 900:
            raise ValueError("lease_seconds_out_of_range")
        self.repository = repository
        self.principal = principal
        self.executor = executor
        self.lease_seconds = lease_seconds

    def run_once(self) -> dict[str, Any] | None:
        """Process at most one job; return its final or retry state."""

        claim = self.repository.claim_next(self.principal, lease_seconds=self.lease_seconds)
        if claim is None:
            return None
        lease_token = str(claim.pop("lease_token"))
        payload = dict(claim.pop("payload"))
        context = WorkerContext(
            job_id=claim["job_id"],
            run_id=claim["run_id"],
            attempt_count=int(claim["attempt_count"]),
            _cancel_probe=lambda: bool(
                (
                    self.repository.get_job(
                        self.principal,
                        claim["job_id"],
                        tenant_worker=True,
                    )
                    or {}
                ).get("cancel_requested")
            ),
            _heartbeat=lambda: self.repository.heartbeat(
                self.principal,
                job_id=claim["job_id"],
                lease_token=lease_token,
                lease_seconds=self.lease_seconds,
            ),
        )
        try:
            if context.cancel_requested:
                return self.repository.complete(
                    self.principal,
                    job_id=claim["job_id"],
                    lease_token=lease_token,
                    result={"status": "cancelled_before_execution"},
                )
            result = self.executor(payload, context)
            if not isinstance(result, dict):
                raise TypeError("worker executor must return a dictionary")
            return self.repository.complete(
                self.principal,
                job_id=claim["job_id"],
                lease_token=lease_token,
                result=result,
            )
        except Exception as exc:
            try:
                return self.repository.fail(
                    self.principal,
                    job_id=claim["job_id"],
                    lease_token=lease_token,
                    error_code=type(exc).__name__,
                    retry_delay_seconds=5,
                )
            except QueueLeaseError:
                # Another worker may safely recover an expired lease; never force-complete it.
                return self.repository.get_job(
                    self.principal,
                    claim["job_id"],
                    tenant_worker=True,
                )
