from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Response
import pytest
from starlette.requests import Request

from apps.api.dependencies import get_production_auth, get_production_runtime
from apps.api.main import app
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
)
from klara.production import AuthConfig, AuthService, ProductionRepository, ProductionRuntimeService, TrajectoryExportService


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
    assert "/api/production/runs" in {route.path for route in app.routes}
    with pytest.raises(HTTPException) as unauthenticated:
        production_principal(None, auth)
    assert unauthenticated.value.status_code == 401
    alice = production_principal(f"Bearer {auth.issue(tenant_id='tenant-a', user_id='alice', roles=('owner', 'operator'))}", auth)
    bob = production_principal(f"Bearer {auth.issue(tenant_id='tenant-a', user_id='bob', roles=('owner', 'operator'))}", auth)
    worker = production_principal(f"Bearer {auth.issue(tenant_id='tenant-a', user_id='worker', roles=('worker',))}", auth)
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


def test_dev_token_endpoint_is_local_and_production_role_checks_apply(tmp_path: Path) -> None:
    auth = AuthService(AuthConfig(mode="development", signing_key=b"q" * 32))
    repository = ProductionRepository(tmp_path / "production.sqlite3")
    service = ProductionRuntimeService(repository, TrajectoryExportService(repository, tmp_path / "exports", allowed_trace_roots=(tmp_path,)))
    response = issue_dev_token(DevTokenRequest(tenant_id="tenant-a", user_id="alice", roles=["owner"]), _request(), auth)
    owner = production_principal(f"Bearer {response['access_token']}", auth)
    with pytest.raises(HTTPException) as forbidden:
        claim_job(LeaseRequest(lease_seconds=60), _request(), owner, service)
    assert forbidden.value.status_code == 403
