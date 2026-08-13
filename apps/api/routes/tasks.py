from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException

from apps.api.dependencies import get_task_scope, get_task_service
from apps.api.schemas import (
    CreateTaskRequest,
    TaskArtifactRequest,
    TaskBlockRequest,
    TaskCheckpointRequest,
    TaskClaimRequest,
    TaskClaimResponse,
    TaskDetailResponse,
    TaskFailRequest,
    TaskHeartbeatRequest,
    TaskLeaseRequest,
    TaskListResponse,
    TaskProgressRequest,
    TaskStateResponse,
)
from klara.tasks import (
    DurableTaskService,
    TaskLeaseError,
    TaskNotFoundError,
    TaskScope,
    TaskTransitionError,
    TaskWriteConflict,
)


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse)
def list_tasks(
    service: DurableTaskService = Depends(get_task_service),
    scope: TaskScope = Depends(get_task_scope),
):
    tasks = [task.to_public_dict() for task in service.list(scope=scope)]
    return TaskListResponse(
        schema_version="klara.durable-task-list.v1",
        tasks=tasks,
        counts_by_state=dict(Counter(str(task["state"]) for task in tasks)),
    )


@router.post("", response_model=TaskStateResponse)
def create_task(
    request: CreateTaskRequest,
    service: DurableTaskService = Depends(get_task_service),
    scope: TaskScope = Depends(get_task_scope),
):
    try:
        task = service.create(
            scope=scope,
            title=request.title,
            description=request.description,
            dependency_ids=tuple(request.dependency_ids),
            parent_task_id=request.parent_task_id,
            required_artifacts=tuple(request.required_artifacts),
            required_evidence=tuple(request.required_evidence),
            max_attempts=request.max_attempts,
        )
        return _state(task)
    except TaskTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/{task_id}", response_model=TaskDetailResponse)
def task_detail(
    task_id: str,
    service: DurableTaskService = Depends(get_task_service),
    scope: TaskScope = Depends(get_task_scope),
):
    try:
        return TaskDetailResponse.model_validate(service.detail(scope=scope, task_id=task_id))
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task_not_found") from None


@router.post("/{task_id}/claim", response_model=TaskClaimResponse)
def claim_task(
    task_id: str,
    request: TaskClaimRequest,
    service: DurableTaskService = Depends(get_task_service),
    scope: TaskScope = Depends(get_task_scope),
):
    try:
        claim = service.claim(
            scope=scope,
            task_id=task_id,
            worker_id=request.worker_id,
            lease_seconds=request.lease_seconds,
        )
        return TaskClaimResponse(
            schema_version="klara.durable-task-claim.v1",
            **claim.to_owner_dict(),
        )
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task_not_found") from None
    except (TaskLeaseError, TaskTransitionError, TaskWriteConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{task_id}/heartbeat", response_model=TaskStateResponse)
def heartbeat_task(task_id: str, request: TaskHeartbeatRequest, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    return _leased(lambda: service.heartbeat(scope=scope, task_id=task_id, lease_token=request.lease_token, lease_seconds=request.lease_seconds))


@router.post("/{task_id}/progress", response_model=TaskStateResponse)
def progress_task(task_id: str, request: TaskProgressRequest, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    return _leased(lambda: service.progress(scope=scope, task_id=task_id, lease_token=request.lease_token, progress=request.progress, current_step=request.current_step))


@router.post("/{task_id}/checkpoint")
def checkpoint_task(task_id: str, request: TaskCheckpointRequest, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    try:
        checkpoint = service.checkpoint(scope=scope, task_id=task_id, lease_token=request.lease_token, summary=request.summary, payload=request.payload)
        return {"schema_version": "klara.durable-task-checkpoint.v1", "checkpoint": checkpoint.to_public_dict()}
    except (TaskLeaseError, TaskTransitionError, TaskWriteConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{task_id}/artifacts")
def add_task_artifact(task_id: str, request: TaskArtifactRequest, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    try:
        artifact = service.add_artifact(scope=scope, task_id=task_id, lease_token=request.lease_token, name=request.name, uri=request.uri, media_type=request.media_type, sha256=request.sha256, is_evidence=request.is_evidence)
        return {"schema_version": "klara.durable-task-artifact.v1", "artifact": artifact.to_public_dict()}
    except (TaskLeaseError, TaskTransitionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{task_id}/pause", response_model=TaskStateResponse)
def pause_task(task_id: str, request: TaskLeaseRequest, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    return _leased(lambda: service.pause(scope=scope, task_id=task_id, lease_token=request.lease_token))


@router.post("/{task_id}/block", response_model=TaskStateResponse)
def block_task(task_id: str, request: TaskBlockRequest, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    return _leased(lambda: service.block(scope=scope, task_id=task_id, lease_token=request.lease_token, reason=request.reason))


@router.post("/{task_id}/fail", response_model=TaskStateResponse)
def fail_task(task_id: str, request: TaskFailRequest, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    return _leased(lambda: service.fail(scope=scope, task_id=task_id, lease_token=request.lease_token, code=request.code, message=request.message))


@router.post("/{task_id}/complete", response_model=TaskStateResponse)
def complete_task(task_id: str, request: TaskLeaseRequest, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    return _leased(lambda: service.complete(scope=scope, task_id=task_id, lease_token=request.lease_token))


@router.post("/{task_id}/resume", response_model=TaskStateResponse)
def resume_task(task_id: str, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    return _plain(lambda: service.resume(scope=scope, task_id=task_id))


@router.post("/{task_id}/retry", response_model=TaskStateResponse)
def retry_task(task_id: str, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    return _plain(lambda: service.retry(scope=scope, task_id=task_id))


@router.post("/{task_id}/cancel", response_model=TaskStateResponse)
def cancel_task(task_id: str, service: DurableTaskService = Depends(get_task_service), scope: TaskScope = Depends(get_task_scope)):
    return _plain(lambda: service.cancel(scope=scope, task_id=task_id))


def _state(task) -> TaskStateResponse:
    return TaskStateResponse(schema_version="klara.durable-task.v1", task=task.to_public_dict())


def _leased(callable_):
    try:
        return _state(callable_())
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task_not_found") from None
    except (TaskLeaseError, TaskTransitionError, TaskWriteConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


def _plain(callable_):
    try:
        return _state(callable_())
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task_not_found") from None
    except (TaskTransitionError, TaskWriteConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
