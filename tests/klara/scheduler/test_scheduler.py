from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from klara.scheduler import (
    MisfirePolicy,
    OccurrenceStatus,
    OverlapPolicy,
    ScheduleKind,
    ScheduleOccurrence,
    SchedulerService,
    ScheduleStatus,
    ScheduleValidationError,
    SQLiteScheduleRepository,
)
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope, TaskState


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def runtime(tmp_path):
    clock = Clock(datetime(2026, 1, 2, 12, 0, tzinfo=UTC))
    scope = TaskScope(tenant_id="tenant-a", owner_id="owner-a", agent_id="klara")
    tasks = DurableTaskService(
        SQLiteTaskRepository(tmp_path / "tasks.sqlite3"), now_fn=clock
    )
    repository = SQLiteScheduleRepository(tmp_path / "schedules.sqlite3")
    scheduler = SchedulerService(repository, tasks, now_fn=clock)
    return clock, scope, tasks, repository, scheduler


def create_once(runtime, **changes):
    clock, scope, _tasks, _repository, scheduler = runtime
    values = {
        "scope": scope,
        "title": "Prepare daily brief",
        "task_description": "Summarize the verified queue.",
        "session_id": "session-1",
        "kind": ScheduleKind.ONCE,
        "timezone": "UTC",
        "run_at": clock.value.isoformat(),
    }
    values.update(changes)
    return scheduler.create(**values)


def complete_occurrence(tasks, scope, occurrence):
    assert occurrence.task_id
    claim = tasks.claim(
        scope=scope, task_id=occurrence.task_id, worker_id="test-worker", lease_seconds=60
    )
    return tasks.complete(
        scope=scope, task_id=occurrence.task_id, lease_token=claim.lease_token
    )


def test_once_tick_reuses_durable_task_and_is_duplicate_safe(runtime):
    _clock, scope, tasks, repository, scheduler = runtime
    schedule = create_once(runtime)
    dispatched: list[str] = []

    first = scheduler.tick(
        scope=scope,
        worker_id="worker-1",
        dispatcher=lambda _schedule, occurrence: dispatched.append(occurrence.task_id or ""),
    )
    second = scheduler.tick(scope=scope, worker_id="worker-2")

    assert len(first.enqueued) == 1
    occurrence = first.enqueued[0]
    assert occurrence.status is OccurrenceStatus.ENQUEUED
    assert tasks.get(scope=scope, task_id=occurrence.task_id or "").state is TaskState.READY
    assert dispatched == [occurrence.task_id]
    assert not second.enqueued
    assert len(repository.list_occurrences(scope, schedule.schedule_id)) == 1
    assert scheduler.get(scope=scope, schedule_id=schedule.schedule_id).status is ScheduleStatus.COMPLETED


def test_terminal_notification_is_durable_and_redelivered_after_callback_failure(runtime):
    _clock, scope, tasks, repository, scheduler = runtime
    create_once(runtime)
    occurrence = scheduler.tick(scope=scope, worker_id="worker").enqueued[0]
    complete_occurrence(tasks, scope, occurrence)

    def fail_delivery(_notification):
        raise RuntimeError("chat projection unavailable")

    with pytest.raises(RuntimeError, match="chat projection unavailable"):
        scheduler.tick(scope=scope, worker_id="worker", notifier=fail_delivery)
    assert len(repository.list_pending_notifications(scope)) == 1

    delivered: list[str] = []
    result = scheduler.tick(
        scope=scope,
        worker_id="worker",
        notifier=lambda notification: delivered.append(notification.notification_id),
    )
    assert delivered == [result.notified[0].notification_id]
    assert not repository.list_pending_notifications(scope)
    assert scheduler.state(scope=scope)["notifications"][0]["delivered_at"]


def test_misfire_skip_records_audit_without_creating_task(runtime):
    clock, scope, tasks, repository, scheduler = runtime
    schedule = create_once(
        runtime,
        run_at=(clock.value - timedelta(hours=1)).isoformat(),
        misfire_policy=MisfirePolicy.SKIP,
        misfire_grace_seconds=30,
    )
    result = scheduler.tick(scope=scope, worker_id="worker")
    assert [item.status for item in result.skipped] == [OccurrenceStatus.SKIPPED_MISFIRE]
    assert tasks.list(scope=scope) == []
    assert repository.list_occurrences(scope, schedule.schedule_id)[0].task_id is None


def test_overlap_queue_one_runs_exactly_one_deferred_occurrence(runtime):
    _clock, scope, tasks, _repository, scheduler = runtime
    schedule = create_once(runtime, overlap_policy=OverlapPolicy.QUEUE_ONE)
    dispatched: list[str] = []
    callback = lambda _schedule, occurrence: dispatched.append(occurrence.task_id or "")
    first = scheduler.run_now(scope=scope, schedule_id=schedule.schedule_id, dispatcher=callback)
    overlap_a = scheduler.run_now(scope=scope, schedule_id=schedule.schedule_id, dispatcher=callback)
    overlap_b = scheduler.run_now(scope=scope, schedule_id=schedule.schedule_id, dispatcher=callback)
    assert overlap_a.status is OccurrenceStatus.SKIPPED_OVERLAP
    assert overlap_b.occurrence_id == overlap_a.occurrence_id
    assert scheduler.get(scope=scope, schedule_id=schedule.schedule_id).queued_overlap

    complete_occurrence(tasks, scope, first)
    result = scheduler.tick(scope=scope, worker_id="worker", dispatcher=callback)
    occurrences = scheduler.repository.list_occurrences(scope, schedule.schedule_id)
    active = [item for item in occurrences if item.status is OccurrenceStatus.ENQUEUED]
    assert len(active) == 1
    assert len(dispatched) == 2
    assert result.notified == ()  # no notifier was provided, delivery stays pending
    assert not scheduler.get(scope=scope, schedule_id=schedule.schedule_id).queued_overlap


def test_reserved_occurrence_recovers_after_process_restart(runtime):
    clock, scope, tasks, repository, scheduler = runtime
    schedule = create_once(runtime)
    reserved = ScheduleOccurrence(
        occurrence_id="occurrence_crash_window",
        schedule_id=schedule.schedule_id,
        task_id="task_occ_crash_window",
        scheduled_for=clock.value.isoformat(),
        status=OccurrenceStatus.RESERVED,
        trigger="scheduled",
        created_at=clock.value.isoformat(),
        updated_at=clock.value.isoformat(),
    )
    repository.reserve_occurrence(scope, reserved)
    restarted = SchedulerService(repository, tasks, now_fn=clock)
    recovered = restarted.tick(scope=scope, worker_id="restart-worker").recovered
    assert [item.occurrence_id for item in recovered] == [reserved.occurrence_id]
    assert tasks.get(scope=scope, task_id=reserved.task_id or "").state is TaskState.READY


def test_enqueued_occurrence_is_redispatched_after_process_restart(runtime):
    _clock, scope, _tasks, repository, scheduler = runtime
    create_once(runtime)
    occurrence = scheduler.tick(scope=scope, worker_id="first-process").enqueued[0]
    restarted = SchedulerService(repository, scheduler.task_service, now_fn=scheduler._now_fn)
    dispatched: list[str] = []
    result = restarted.tick(
        scope=scope,
        worker_id="new-process",
        dispatcher=lambda _schedule, item: dispatched.append(item.occurrence_id),
    )
    assert occurrence.occurrence_id in dispatched
    assert occurrence.occurrence_id in [item.occurrence_id for item in result.recovered]


@pytest.mark.parametrize(
    ("now", "local_time", "expected"),
    [
        (
            datetime(2026, 3, 7, 12, tzinfo=UTC),
            "02:30",
            "2026-03-08T07:00:00+00:00",
        ),
        (
            datetime(2026, 10, 31, 12, tzinfo=UTC),
            "01:30",
            "2026-11-01T05:30:00+00:00",
        ),
    ],
)
def test_daily_dst_policy_moves_gap_forward_and_chooses_first_fold(
    tmp_path, now, local_time, expected
):
    clock = Clock(now)
    scope = TaskScope(tenant_id="t", owner_id="u", agent_id="klara")
    tasks = DurableTaskService(SQLiteTaskRepository(tmp_path / "tasks.sqlite3"), now_fn=clock)
    scheduler = SchedulerService(
        SQLiteScheduleRepository(tmp_path / "schedules.sqlite3"), tasks, now_fn=clock
    )
    schedule = scheduler.create(
        scope=scope,
        title="DST schedule",
        task_description="test",
        session_id=None,
        kind=ScheduleKind.DAILY,
        timezone="America/New_York",
        local_time=local_time,
    )
    assert schedule.next_run_at == expected


def test_pause_resume_cancel_and_scope_isolation(runtime):
    _clock, scope, _tasks, _repository, scheduler = runtime
    schedule = create_once(runtime)
    paused = scheduler.pause(scope=scope, schedule_id=schedule.schedule_id)
    assert paused.status is ScheduleStatus.PAUSED
    resumed = scheduler.resume(scope=scope, schedule_id=schedule.schedule_id)
    assert resumed.status is ScheduleStatus.ACTIVE
    cancelled = scheduler.cancel(scope=scope, schedule_id=schedule.schedule_id)
    assert cancelled.status is ScheduleStatus.CANCELLED
    other_scope = replace(scope, tenant_id="tenant-b")
    assert scheduler.list(scope=other_scope) == []


def test_validation_rejects_invalid_timezone_and_short_interval(runtime):
    _clock, scope, _tasks, _repository, scheduler = runtime
    with pytest.raises(ScheduleValidationError, match="timezone_invalid"):
        scheduler.create(
            scope=scope,
            title="bad",
            task_description="",
            session_id=None,
            kind=ScheduleKind.DAILY,
            timezone="Mars/Olympus",
            local_time="12:00",
        )
    with pytest.raises(ScheduleValidationError, match="minimum_60_seconds"):
        scheduler.create(
            scope=scope,
            title="bad",
            task_description="",
            session_id=None,
            kind=ScheduleKind.INTERVAL,
            timezone="UTC",
            interval_seconds=10,
        )
