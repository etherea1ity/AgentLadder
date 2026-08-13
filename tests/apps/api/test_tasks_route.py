from __future__ import annotations

from fastapi import HTTPException

from apps.api.main import app
from apps.api.routes.tasks import (
    add_task_artifact,
    claim_task,
    complete_task,
    create_task,
    list_tasks,
    progress_task,
    task_detail,
)
from apps.api.schemas import (
    CreateTaskRequest,
    TaskArtifactRequest,
    TaskClaimRequest,
    TaskLeaseRequest,
    TaskProgressRequest,
)
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope


def test_task_api_real_lifecycle_and_safe_detail(tmp_path) -> None:
    service = DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3"))
    scope = TaskScope(tenant_id="test-tenant", owner_id="test-user")
    paths = {route.path for route in app.routes}
    assert "/api/tasks" in paths
    assert "/api/tasks/{task_id}/claim" in paths
    created = create_task(
        CreateTaskRequest(
            title="Build release evidence",
            required_artifacts=["report"],
            required_evidence=["sources"],
        ),
        service,
        scope,
    )
    task_id = created.task["task_id"]
    claim = claim_task(task_id, TaskClaimRequest(worker_id="api-test"), service, scope)
    lease = claim.lease_token
    assert "lease_token_sha256" not in str(claim.task)
    progress_task(
        task_id,
        TaskProgressRequest(lease_token=lease, progress=65, current_step="Verify"),
        service,
        scope,
    )
    for name, evidence in (("report", False), ("sources", True)):
        artifact = add_task_artifact(
            task_id,
            TaskArtifactRequest(
                lease_token=lease,
                name=name,
                uri=f"https://example.com/{name}?token=hidden",
                media_type="application/json",
                sha256=("a" if evidence else "b") * 64,
                is_evidence=evidence,
            ),
            service,
            scope,
        )
        assert "token" not in str(artifact)
    completed = complete_task(
        task_id, TaskLeaseRequest(lease_token=lease), service, scope
    )
    assert completed.task["state"] == "completed"
    detail = task_detail(task_id, service, scope)
    assert detail.attempts[0]["outcome"] == "completed"
    listed = list_tasks(service, scope)
    assert listed.counts_by_state == {"completed": 1}


def test_task_api_conflicts_and_owner_isolation(tmp_path) -> None:
    service = DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3"))
    owner = TaskScope(tenant_id="test-tenant", owner_id="test-user")
    task = service.create(scope=owner, title="Private task")
    claim_task(task.task_id, TaskClaimRequest(worker_id="w"), service, owner)
    try:
        claim_task(task.task_id, TaskClaimRequest(worker_id="w2"), service, owner)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("duplicate claim must conflict")
    outsider = TaskScope(tenant_id="other", owner_id="test-user")
    try:
        task_detail(task.task_id, service, outsider)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("cross-tenant detail must be hidden")
    assert list_tasks(service, outsider).tasks == []
