"""Tenant-scoped scheduler API projected from the durable Chapter 15 state."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from apps.api.dependencies import (
    get_run_service,
    get_scheduler_runner,
    get_scheduler_service,
    get_store,
    get_task_scope,
)
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.scheduler_runner import SchedulerRunner
from klara.scheduler import (
    MisfirePolicy,
    OverlapPolicy,
    ScheduleKind,
    ScheduleNotFoundError,
    SchedulerService,
    ScheduleValidationError,
)
from klara.tasks import TaskScope, TaskTransitionError


router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class CreateScheduleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    task_description: str = Field(default="", max_length=4000)
    session_id: str
    kind: ScheduleKind
    timezone: str = Field(min_length=1, max_length=120)
    run_at: str | None = None
    local_time: str | None = None
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    interval_seconds: int | None = None
    misfire_policy: MisfirePolicy = MisfirePolicy.FIRE_ONCE
    misfire_grace_seconds: int = Field(default=300, ge=0, le=604800)
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP


@router.get("")
def scheduler_state(
    service: SchedulerService = Depends(get_scheduler_service),
    scope: TaskScope = Depends(get_task_scope),
):
    return service.state(scope=scope)


@router.post("", status_code=201)
def create_schedule(
    request: CreateScheduleRequest,
    service: SchedulerService = Depends(get_scheduler_service),
    scope: TaskScope = Depends(get_task_scope),
    store: JsonlAppStore = Depends(get_store),
):
    if store.get_visible_session(request.session_id) is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    try:
        schedule = service.create(
            scope=scope,
            title=request.title,
            task_description=request.task_description,
            session_id=request.session_id,
            kind=request.kind,
            timezone=request.timezone,
            run_at=request.run_at,
            local_time=request.local_time,
            weekdays=tuple(request.weekdays),
            interval_seconds=request.interval_seconds,
            misfire_policy=request.misfire_policy,
            misfire_grace_seconds=request.misfire_grace_seconds,
            overlap_policy=request.overlap_policy,
        )
        return {"schema_version": "klara.schedule.v1", "schedule": schedule.to_public_dict()}
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/tick")
def tick_scheduler(runner: SchedulerRunner = Depends(get_scheduler_runner)):
    """Run one serialized poll; production also invokes this from the worker."""

    return runner.tick_once().to_public_dict()


@router.post("/occurrences/{occurrence_id}/retry")
def retry_occurrence(
    occurrence_id: str,
    service: SchedulerService = Depends(get_scheduler_service),
    scope: TaskScope = Depends(get_task_scope),
    runner: SchedulerRunner = Depends(get_scheduler_runner),
):
    try:
        occurrence = service.retry_occurrence(
            scope=scope, occurrence_id=occurrence_id, dispatcher=runner.dispatch
        )
        return {"schema_version": "klara.schedule-occurrence.v1", "occurrence": occurrence.to_public_dict()}
    except ScheduleNotFoundError:
        raise HTTPException(status_code=404, detail="schedule_occurrence_not_found") from None
    except (ScheduleValidationError, TaskTransitionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/notifications/{notification_id}/read")
def read_notification(
    notification_id: str,
    service: SchedulerService = Depends(get_scheduler_service),
    scope: TaskScope = Depends(get_task_scope),
):
    try:
        notification = service.mark_notification_read(
            scope=scope, notification_id=notification_id
        )
        return {"schema_version": "klara.schedule-notification.v1", "notification": notification.to_public_dict()}
    except ScheduleNotFoundError:
        raise HTTPException(status_code=404, detail="schedule_notification_not_found") from None


@router.post("/{schedule_id}/{action}")
def transition_schedule(
    schedule_id: str,
    action: str,
    service: SchedulerService = Depends(get_scheduler_service),
    scope: TaskScope = Depends(get_task_scope),
    runner: SchedulerRunner = Depends(get_scheduler_runner),
    run_service: RunService = Depends(get_run_service),
):
    try:
        if action == "pause":
            schedule = service.pause(scope=scope, schedule_id=schedule_id)
            return {"schema_version": "klara.schedule.v1", "schedule": schedule.to_public_dict()}
        if action == "resume":
            schedule = service.resume(scope=scope, schedule_id=schedule_id)
            return {"schema_version": "klara.schedule.v1", "schedule": schedule.to_public_dict()}
        if action == "cancel":
            active_task_ids = [
                item.task_id
                for item in service.repository.list_occurrences(scope, schedule_id)
                if item.task_id is not None
            ]
            schedule = service.cancel(scope=scope, schedule_id=schedule_id)
            for task_id in active_task_ids:
                run_service.cancel_run(task_id)
            return {"schema_version": "klara.schedule.v1", "schedule": schedule.to_public_dict()}
        if action == "run-now":
            occurrence = service.run_now(
                scope=scope, schedule_id=schedule_id, dispatcher=runner.dispatch
            )
            return {"schema_version": "klara.schedule-occurrence.v1", "occurrence": occurrence.to_public_dict()}
        raise HTTPException(status_code=404, detail="scheduler_action_not_found")
    except ScheduleNotFoundError:
        raise HTTPException(status_code=404, detail="schedule_not_found") from None
    except (ScheduleValidationError, TaskTransitionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
