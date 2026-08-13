"""Authenticated production-shaped session, queue, outbox, and export API."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from apps.api.dependencies import get_production_auth, get_production_identity, get_production_metrics, get_production_runtime
from klara.production import AuthError, AuthService, Principal, ProductionIdentityBoundary, ProductionRuntimeService, QueueConflict, QueueLeaseError, SafeRuntimeMetrics


router = APIRouter(prefix="/api/production", tags=["production"])


class DevTokenRequest(BaseModel):
    tenant_id: str
    user_id: str
    roles: list[str] = Field(default_factory=lambda: ["owner", "operator"])


class SessionRequest(BaseModel):
    title: str = "New production session"


class RunRequest(BaseModel):
    session_id: str
    question: str = Field(min_length=1, max_length=32000)
    model: str | None = Field(default=None, max_length=160)
    maximum_steps: int = Field(default=12, ge=1, le=64)


class LeaseRequest(BaseModel):
    lease_seconds: int = 120


class LeaseActionRequest(LeaseRequest):
    lease_token: str = Field(min_length=32, max_length=256)


class CompleteRequest(BaseModel):
    lease_token: str = Field(min_length=32, max_length=256)
    result: dict[str, Any] = Field(default_factory=dict)


class FailRequest(BaseModel):
    lease_token: str = Field(min_length=32, max_length=256)
    error_code: str
    retry_delay_seconds: int = Field(default=5, ge=0, le=3600)


class OutboxAckRequest(BaseModel):
    delivery_token: str = Field(min_length=32, max_length=256)


class ExportRequest(BaseModel):
    trace_path: str = Field(min_length=1, max_length=500)


class RevokeCredentialRequest(BaseModel):
    reason: str = Field(default="self_revoked", max_length=80)


class StatePutRequest(BaseModel):
    value: dict[str, Any]
    expected_version: int | None = Field(default=None, ge=0)


class StateDeleteRequest(BaseModel):
    expected_version: int = Field(ge=1)


def production_principal(
    authorization: str | None = Header(default=None),
    identity: ProductionIdentityBoundary = Depends(get_production_identity),
) -> Principal:
    try:
        return identity.verify_authorization(authorization)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from None


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _guard(call):
    try:
        return call()
    except AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except (QueueConflict, QueueLeaseError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/auth/dev-token")
def issue_dev_token(request: DevTokenRequest, raw: Request, auth: AuthService = Depends(get_production_auth)):
    if auth.config.mode != "development":
        raise HTTPException(status_code=404, detail="not_found")
    if raw.client is None or raw.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="development_token_loopback_only")
    return _guard(lambda: {
        "schema_version": "klara.dev-token-response.v1",
        "token_type": "Bearer",
        "expires_in": auth.config.token_ttl_seconds,
        "access_token": auth.issue(tenant_id=request.tenant_id, user_id=request.user_id, roles=request.roles),
    })


@router.get("/whoami")
def whoami(principal: Principal = Depends(production_principal)):
    return principal.to_public_dict()


@router.post("/auth/revoke-current")
def revoke_current_credential(request: RevokeCredentialRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: service.revoke_current_credential(principal, reason=request.reason, request_id=_request_id(raw)))


@router.put("/state/{namespace}/{record_id}")
def put_state(namespace: str, record_id: str, request: StatePutRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: service.put_state(principal, namespace=namespace, record_id=record_id, value=request.value, expected_version=request.expected_version, request_id=_request_id(raw)))


@router.get("/state/{namespace}/{record_id}")
def get_state(namespace: str, record_id: str, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    record = _guard(lambda: service.get_state(principal, namespace=namespace, record_id=record_id))
    if record is None:
        raise HTTPException(status_code=404, detail="state_not_found")
    return record


@router.delete("/state/{namespace}/{record_id}")
def delete_state(namespace: str, record_id: str, request: StateDeleteRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    deleted = _guard(lambda: service.delete_state(principal, namespace=namespace, record_id=record_id, expected_version=request.expected_version, request_id=_request_id(raw)))
    if not deleted:
        raise HTTPException(status_code=409, detail="state_version_conflict_or_not_found")
    return {"schema_version": "klara.production-state-delete.v1", "deleted": True, "record_id": record_id}


@router.post("/sessions", status_code=201)
def create_session(request: SessionRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: service.create_session(principal, title=request.title, request_id=_request_id(raw)))


@router.get("/sessions")
def list_sessions(principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: {"schema_version": "klara.production-session-list.v1", "sessions": service.list_sessions(principal)})


@router.post("/runs", status_code=202)
def enqueue_run(request: RunRequest, raw: Request, response: Response, idempotency_key: str = Header(alias="Idempotency-Key"), principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    def execute():
        job, created = service.enqueue_run(
            principal,
            session_id=request.session_id,
            payload={"question": request.question.strip(), "model": request.model, "maximum_steps": request.maximum_steps},
            idempotency_key=idempotency_key,
            request_id=_request_id(raw),
        )
        response.status_code = 202 if created else 200
        return {"schema_version": "klara.production-enqueue.v1", "created": created, "job": job}
    return _guard(execute)


@router.get("/runs")
def list_runs(principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: {"schema_version": "klara.production-job-list.v1", "jobs": service.list_jobs(principal)})


@router.get("/runs/{job_id}")
def get_run(job_id: str, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    job = _guard(lambda: service.get_job(principal, job_id=job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


@router.get("/runs/{job_id}/events")
def list_run_events(job_id: str, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    events = _guard(lambda: service.list_job_events(principal, job_id=job_id))
    if events is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return {"schema_version": "klara.production-job-events.v1", "events": events}


@router.get("/runs/{job_id}/events/stream")
def stream_run_events(job_id: str, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    initial = _guard(lambda: service.list_job_events(principal, job_id=job_id))
    if initial is None:
        raise HTTPException(status_code=404, detail="job_not_found")

    async def events():
        cursor = 0
        while not await raw.is_disconnected():
            current = await asyncio.to_thread(
                service.list_job_events,
                principal,
                job_id=job_id,
            ) or []
            for event in current:
                if int(event["seq"]) <= cursor:
                    continue
                cursor = int(event["seq"])
                yield f"id: {cursor}\nevent: {event['event_type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["event_type"] in {"job.completed", "job.failed", "job.cancelled", "job.dead_letter"}:
                    return
            await asyncio.sleep(0.2)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/runs/{job_id}/cancel")
def cancel_run(job_id: str, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    job = _guard(lambda: service.cancel(principal, job_id=job_id, request_id=_request_id(raw)))
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


@router.post("/worker/claim")
def claim_job(request: LeaseRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: {"schema_version": "klara.production-claim.v1", "job": service.claim(principal, lease_seconds=request.lease_seconds, request_id=_request_id(raw))})


@router.post("/worker/runs/{job_id}/heartbeat")
def heartbeat(job_id: str, request: LeaseActionRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: service.heartbeat(principal, job_id=job_id, lease_token=request.lease_token, lease_seconds=request.lease_seconds, request_id=_request_id(raw)))


@router.post("/worker/runs/{job_id}/complete")
def complete(job_id: str, request: CompleteRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: service.complete(principal, job_id=job_id, lease_token=request.lease_token, result=request.result, request_id=_request_id(raw)))


@router.post("/worker/runs/{job_id}/fail")
def fail(job_id: str, request: FailRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: service.fail(principal, job_id=job_id, lease_token=request.lease_token, error_code=request.error_code, retry_delay_seconds=request.retry_delay_seconds, request_id=_request_id(raw)))


@router.post("/outbox/claim")
def claim_outbox(request: LeaseRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: {"schema_version": "klara.production-outbox-claim.v1", "event": service.claim_outbox(principal, lease_seconds=request.lease_seconds, request_id=_request_id(raw))})


@router.post("/outbox/{event_id}/acknowledge")
def acknowledge_outbox(event_id: str, request: OutboxAckRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: service.acknowledge_outbox(principal, event_id=event_id, delivery_token=request.delivery_token, request_id=_request_id(raw)))


@router.post("/runs/{job_id}/trajectory-export")
def export_trajectory(job_id: str, request: ExportRequest, raw: Request, principal: Principal = Depends(production_principal), service: ProductionRuntimeService = Depends(get_production_runtime)):
    return _guard(lambda: service.export_trajectory(principal, job_id=job_id, trace_path=request.trace_path, request_id=_request_id(raw)))


@router.get("/metrics")
def metrics(principal: Principal = Depends(production_principal), values: SafeRuntimeMetrics = Depends(get_production_metrics)):
    return _guard(lambda: (principal.require("admin"), values.snapshot().to_dict())[1])
