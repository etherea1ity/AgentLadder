from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Response
import pytest
from starlette.requests import Request

from apps.api.dependencies import get_production_auth, get_production_runtime
from apps.api.main import app
from apps.api.main import production_request_boundary
from apps.api.routes.production import (
    CompleteRequest,
    DevTokenRequest,
    LeaseRequest,
    RunRequest,
    SessionRequest,
    claim_job,
    complete,
    create_session,
    enqueue_run,
    get_run,
    issue_dev_token,
    production_principal,
    revoke_current_credential,
    RevokeCredentialRequest,
    StatePutRequest,
    StateDeleteRequest,
    delete_state,
    get_state,
    put_state,
)
from klara.production import AuthConfig, AuthService, ProductionIdentityBoundary, ProductionRepository, ProductionRuntimeService, TrajectoryExportService


def _request() -> Request:
    request = Request({"type": "http", "headers": [], "client": ("testclient", 50000), "method": "POST", "path": "/api/production/test", "scheme": "http", "server": ("testserver", 80), "query_string": b""})
    request.state.request_id = "req-test"
    return request


def test_production_api_requires_auth_and_hides_cross_owner_rows(tmp_path: Path) -> None:
    auth = AuthService(AuthConfig(mode="development", signing_key=b"z" * 32))
    repository = ProductionRepository(tmp_path / "production.sqlite3")
    service = ProductionRuntimeService(
        repository,
        TrajectoryExportService(repository, tmp_path / "exports", allowed_trace_roots=(tmp_path,)),
    )
    identity = ProductionIdentityBoundary(local=auth, revocations=repository)
    assert "/api/production/runs" in {route.path for route in app.routes}
    with pytest.raises(HTTPException) as unauthenticated:
        production_principal(None, identity)
    assert unauthenticated.value.status_code == 401
    alice_token = auth.issue(tenant_id="tenant-a", user_id="alice", roles=("owner", "operator"))
    alice = production_principal(f"Bearer {alice_token}", identity)
    bob = production_principal(f"Bearer {auth.issue(tenant_id='tenant-a', user_id='bob', roles=('owner', 'operator'))}", identity)
    worker = production_principal(f"Bearer {auth.issue(tenant_id='tenant-a', user_id='worker', roles=('worker',))}", identity)
    session = create_session(SessionRequest(title="Alice"), _request(), alice, service)
    session_id = session["session_id"]
    first_response = Response(status_code=202)
    queued = enqueue_run(RunRequest(session_id=session_id, question="Do the bounded task"), _request(), first_response, "api-request-0001", alice, service)
    assert first_response.status_code == 202
    job_id = queued["job"]["job_id"]
    repeat_response = Response(status_code=202)
    repeated = enqueue_run(RunRequest(session_id=session_id, question="Do the bounded task"), _request(), repeat_response, "api-request-0001", alice, service)
    assert repeat_response.status_code == 200
    assert repeated["job"]["job_id"] == job_id
    with pytest.raises(HTTPException) as hidden:
        get_run(job_id, bob, service)
    assert hidden.value.status_code == 404
    claimed = claim_job(LeaseRequest(lease_seconds=60), _request(), worker, service)
    lease = claimed["job"]["lease_token"]
    completed = complete(job_id, CompleteRequest(lease_token=lease, result={"status": "ok"}), _request(), worker, service)
    assert completed["state"] == "completed"
    state = put_state("plan", "plan-api-1", StatePutRequest(value={"status": "in_progress"}, expected_version=0), _request(), alice, service)
    assert state["version"] == 1
    with pytest.raises(HTTPException) as hidden_state:
        get_state("plan", "plan-api-1", bob, service)
    assert hidden_state.value.status_code == 404
    removed = delete_state("plan", "plan-api-1", StateDeleteRequest(expected_version=1), _request(), alice, service)
    assert removed["deleted"] is True
    revoked = revoke_current_credential(RevokeCredentialRequest(reason="logout"), _request(), alice, service)
    assert revoked["revoked"] is True
    with pytest.raises(HTTPException) as revoked_request:
        production_principal(f"Bearer {alice_token}", identity)
    assert revoked_request.value.status_code == 401
    replacement_token = auth.issue(tenant_id="tenant-a", user_id="alice", roles=("owner",))
    assert production_principal(f"Bearer {replacement_token}", identity).user_id == "alice"


def test_dev_token_endpoint_is_local_and_production_role_checks_apply(tmp_path: Path) -> None:
    auth = AuthService(AuthConfig(mode="development", signing_key=b"q" * 32))
    repository = ProductionRepository(tmp_path / "production.sqlite3")
    service = ProductionRuntimeService(repository, TrajectoryExportService(repository, tmp_path / "exports", allowed_trace_roots=(tmp_path,)))
    identity = ProductionIdentityBoundary(local=auth, revocations=repository)
    response = issue_dev_token(DevTokenRequest(tenant_id="tenant-a", user_id="alice", roles=["owner"]), _request(), auth)
    owner = production_principal(f"Bearer {response['access_token']}", identity)
    with pytest.raises(HTTPException) as forbidden:
        claim_job(LeaseRequest(lease_seconds=60), _request(), owner, service)
    assert forbidden.value.status_code == 403


def test_production_middleware_rejects_cross_site_mutation() -> None:
    import asyncio

    request = Request({
        "type": "http",
        "headers": [(b"sec-fetch-site", b"cross-site")],
        "client": ("outside.example", 50000),
        "method": "POST",
        "path": "/api/production/runs",
        "scheme": "https",
        "server": ("klara.example", 443),
        "query_string": b"",
    })
    called = False

    async def downstream(_request):
        nonlocal called
        called = True
        return Response(status_code=204)

    response = asyncio.run(production_request_boundary(request, downstream))
    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    assert called is False
