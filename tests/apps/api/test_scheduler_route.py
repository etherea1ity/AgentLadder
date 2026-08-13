from __future__ import annotations

from fastapi import HTTPException

from apps.api.main import app
from apps.api.routes.scheduler import (
    CreateScheduleRequest,
    create_schedule,
    scheduler_state,
    transition_schedule,
)
from apps.api.services.app_store import JsonlAppStore
from klara.scheduler import ScheduleKind, SchedulerService, SQLiteScheduleRepository
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope


class RunnerStub:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch(self, _schedule, occurrence) -> None:
        self.dispatched.append(occurrence.occurrence_id)


class RunServiceStub:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def cancel_run(self, task_id: str) -> None:
        self.cancelled.append(task_id)


def test_scheduler_api_real_state_and_actions(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    session = store.create_session()
    scope = TaskScope(tenant_id="test-tenant", owner_id="test-user")
    tasks = DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3"))
    service = SchedulerService(
        SQLiteScheduleRepository(tmp_path / "scheduler.sqlite3"), tasks
    )
    runner = RunnerStub()
    run_service = RunServiceStub()
    paths = {route.path for route in app.routes}
    assert "/api/scheduler" in paths
    assert "/api/scheduler/{schedule_id}/{action}" in paths

    created = create_schedule(
        CreateScheduleRequest(
            title="Morning brief",
            task_description="Summarize verified work.",
            session_id=session.session_id,
            kind=ScheduleKind.DAILY,
            timezone="Asia/Shanghai",
            local_time="08:30",
        ),
        service,
        scope,
        store,
    )
    schedule_id = created["schedule"]["schedule_id"]
    assert created["schedule"]["next_run_at"]
    paused = transition_schedule(
        schedule_id, "pause", service, scope, runner, run_service
    )
    assert paused["schedule"]["status"] == "paused"
    transition_schedule(schedule_id, "resume", service, scope, runner, run_service)
    occurrence = transition_schedule(
        schedule_id, "run-now", service, scope, runner, run_service
    )
    assert occurrence["occurrence"]["status"] == "enqueued"
    assert runner.dispatched == [occurrence["occurrence"]["occurrence_id"]]
    state = scheduler_state(service, scope)
    assert state["schema_version"] == "klara.scheduler-state.v1"
    assert len(state["schedules"]) == 1


def test_scheduler_api_rejects_missing_session_and_hides_owner(tmp_path) -> None:
    store = JsonlAppStore(tmp_path / "app")
    owner = TaskScope(tenant_id="tenant-a", owner_id="owner-a")
    tasks = DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3"))
    service = SchedulerService(SQLiteScheduleRepository(tmp_path / "s.sqlite3"), tasks)
    request = CreateScheduleRequest(
        title="Private schedule",
        task_description="",
        session_id="missing",
        kind=ScheduleKind.ONCE,
        timezone="UTC",
        run_at="2027-01-01T00:00:00+00:00",
    )
    try:
        create_schedule(request, service, owner, store)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("missing session must fail closed")
    outsider = TaskScope(tenant_id="tenant-b", owner_id="owner-a")
    assert scheduler_state(service, outsider)["schedules"] == []
