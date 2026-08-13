"""Timezone-aware scheduler built on Chapter 14 durable tasks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
import hashlib
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from klara.scheduler.models import (
    MisfirePolicy,
    OccurrenceStatus,
    OverlapPolicy,
    Schedule,
    ScheduleKind,
    ScheduleNotification,
    ScheduleOccurrence,
    SchedulerTickResult,
    ScheduleStatus,
    new_schedule_id,
)
from klara.scheduler.repository import SQLiteScheduleRepository
from klara.tasks import (
    DurableTaskService,
    TaskNotFoundError,
    TaskScope,
    TaskState,
    TaskTransitionError,
)


class ScheduleNotFoundError(LookupError):
    pass


class ScheduleValidationError(ValueError):
    pass


DispatchCallback = Callable[[Schedule, ScheduleOccurrence], None]
NotificationCallback = Callable[[ScheduleNotification], None]


class SchedulerService:
    """Calculate due work and persist idempotent durable-task occurrences."""

    MAX_HORIZON_DAYS = 370
    LEASE_SECONDS = 30

    def __init__(
        self,
        repository: SQLiteScheduleRepository,
        task_service: DurableTaskService,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.task_service = task_service
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def create(
        self,
        *,
        scope: TaskScope,
        title: str,
        task_description: str,
        session_id: str | None,
        kind: ScheduleKind,
        timezone: str,
        run_at: str | None = None,
        local_time: str | None = None,
        weekdays: tuple[int, ...] = (),
        interval_seconds: int | None = None,
        misfire_policy: MisfirePolicy = MisfirePolicy.FIRE_ONCE,
        misfire_grace_seconds: int = 300,
        overlap_policy: OverlapPolicy = OverlapPolicy.SKIP,
    ) -> Schedule:
        clean_title = " ".join(title.split())[:160]
        if not clean_title:
            raise ScheduleValidationError("schedule_title_required")
        zone = _zone(timezone)
        clean_weekdays = tuple(sorted(set(weekdays)))
        if any(day < 0 or day > 6 for day in clean_weekdays):
            raise ScheduleValidationError("schedule_weekday_out_of_range")
        if kind is ScheduleKind.INTERVAL and (
            interval_seconds is None or interval_seconds < 60
        ):
            raise ScheduleValidationError("schedule_interval_minimum_60_seconds")
        if kind in {ScheduleKind.DAILY, ScheduleKind.WEEKLY}:
            _local_clock(local_time)
        if kind is ScheduleKind.WEEKLY and not clean_weekdays:
            raise ScheduleValidationError("schedule_weekly_requires_weekdays")
        if kind is ScheduleKind.ONCE and run_at is None:
            raise ScheduleValidationError("schedule_once_requires_run_at")
        if misfire_grace_seconds < 0 or misfire_grace_seconds > 7 * 24 * 3600:
            raise ScheduleValidationError("schedule_misfire_grace_out_of_range")
        now = self._now_dt()
        anchor = _aware_utc(run_at) if run_at else now
        draft = Schedule(
            schedule_id=new_schedule_id(),
            scope=scope,
            title=clean_title,
            task_description=" ".join(task_description.split())[:4000],
            session_id=session_id,
            kind=kind,
            timezone=zone.key,
            status=ScheduleStatus.ACTIVE,
            run_at=anchor.isoformat() if run_at else None,
            local_time=local_time,
            weekdays=clean_weekdays,
            interval_seconds=interval_seconds,
            misfire_policy=misfire_policy,
            misfire_grace_seconds=misfire_grace_seconds,
            overlap_policy=overlap_policy,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        next_run = _first_run(draft, now=now)
        if next_run is None:
            raise ScheduleValidationError("schedule_has_no_next_run")
        schedule = replace(draft, next_run_at=next_run.isoformat())
        self.repository.create_schedule(schedule)
        return schedule

    def get(self, *, scope: TaskScope, schedule_id: str) -> Schedule:
        schedule = self.repository.get_schedule(scope, schedule_id)
        if schedule is None:
            raise ScheduleNotFoundError("schedule_not_found")
        return schedule

    def list(self, *, scope: TaskScope) -> list[Schedule]:
        return self.repository.list_schedules(scope)

    def pause(self, *, scope: TaskScope, schedule_id: str) -> Schedule:
        schedule = self.get(scope=scope, schedule_id=schedule_id)
        if schedule.status is not ScheduleStatus.ACTIVE:
            raise ScheduleValidationError("schedule_not_active")
        return self._save(schedule, status=ScheduleStatus.PAUSED)

    def resume(self, *, scope: TaskScope, schedule_id: str) -> Schedule:
        schedule = self.get(scope=scope, schedule_id=schedule_id)
        if schedule.status is not ScheduleStatus.PAUSED:
            raise ScheduleValidationError("schedule_not_paused")
        now = self._now_dt()
        next_run = _first_run(schedule, now=now)
        if next_run is None:
            return self._save(schedule, status=ScheduleStatus.COMPLETED, next_run_at=None)
        return self._save(
            schedule, status=ScheduleStatus.ACTIVE, next_run_at=next_run.isoformat()
        )

    def cancel(self, *, scope: TaskScope, schedule_id: str) -> Schedule:
        schedule = self.get(scope=scope, schedule_id=schedule_id)
        if schedule.status is ScheduleStatus.CANCELLED:
            return schedule
        for occurrence in self.repository.list_occurrences(scope, schedule_id):
            if occurrence.status is OccurrenceStatus.ENQUEUED and occurrence.task_id:
                try:
                    task = self.task_service.get(scope=scope, task_id=occurrence.task_id)
                    if task.state not in {TaskState.COMPLETED, TaskState.CANCELLED}:
                        self.task_service.cancel(scope=scope, task_id=task.task_id)
                except TaskNotFoundError:
                    pass
        return self._save(
            schedule, status=ScheduleStatus.CANCELLED, next_run_at=None
        )

    def run_now(
        self,
        *,
        scope: TaskScope,
        schedule_id: str,
        dispatcher: DispatchCallback | None = None,
    ) -> ScheduleOccurrence:
        schedule = self.get(scope=scope, schedule_id=schedule_id)
        if schedule.status is ScheduleStatus.CANCELLED:
            raise ScheduleValidationError("schedule_cancelled")
        return self._materialize(
            schedule,
            scheduled_for=self._now_dt(),
            trigger="manual",
            dispatcher=dispatcher,
            advance_schedule=False,
        )

    def retry_occurrence(
        self,
        *,
        scope: TaskScope,
        occurrence_id: str,
        dispatcher: DispatchCallback | None = None,
    ) -> ScheduleOccurrence:
        occurrence = next(
            (
                item
                for item in self.repository.list_occurrences(scope)
                if item.occurrence_id == occurrence_id
            ),
            None,
        )
        if occurrence is None or occurrence.task_id is None:
            raise ScheduleNotFoundError("schedule_occurrence_not_found")
        if occurrence.status is not OccurrenceStatus.FAILED:
            raise ScheduleValidationError("schedule_occurrence_not_failed")
        task = self.task_service.retry(scope=scope, task_id=occurrence.task_id)
        schedule = self.get(scope=scope, schedule_id=occurrence.schedule_id)
        updated = replace(
            occurrence,
            status=OccurrenceStatus.ENQUEUED,
            updated_at=self._now(),
            completed_at=None,
            result="retrying",
        )
        self.repository.save_occurrence(scope, updated)
        if dispatcher is not None:
            dispatcher(schedule, updated)
        return updated

    def tick(
        self,
        *,
        scope: TaskScope,
        worker_id: str,
        dispatcher: DispatchCallback | None = None,
        notifier: NotificationCallback | None = None,
    ) -> SchedulerTickResult:
        now = self._now_dt()
        notified = self._sync_terminals(
            scope, dispatcher=dispatcher, notifier=notifier
        )
        recovered = self._recover_reserved(scope, dispatcher=dispatcher)
        enqueued: list[ScheduleOccurrence] = []
        skipped: list[ScheduleOccurrence] = []
        contention = 0
        for schedule in self.repository.list_due(scope, now.isoformat()):
            lease = self.repository.acquire_lease(
                scope=scope,
                schedule_id=schedule.schedule_id,
                worker_id=worker_id,
                now=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.LEASE_SECONDS)).isoformat(),
            )
            if lease is None:
                contention += 1
                continue
            try:
                current = self.get(scope=scope, schedule_id=schedule.schedule_id)
                if current.status is not ScheduleStatus.ACTIVE or current.next_run_at is None:
                    continue
                scheduled_for = _aware_utc(current.next_run_at)
                late_seconds = max(0, int((now - scheduled_for).total_seconds()))
                if (
                    late_seconds > current.misfire_grace_seconds
                    and current.misfire_policy is MisfirePolicy.SKIP
                ):
                    occurrence = self._skip(
                        current,
                        scheduled_for=scheduled_for,
                        status=OccurrenceStatus.SKIPPED_MISFIRE,
                        result=f"misfire_late_by_{late_seconds}s",
                    )
                    skipped.append(occurrence)
                    self._advance(
                        current,
                        scheduled_for=scheduled_for,
                        now=now,
                        catch_up=False,
                        occurrence_id=occurrence.occurrence_id,
                    )
                    continue
                occurrence = self._materialize(
                    current,
                    scheduled_for=scheduled_for,
                    trigger="misfire" if late_seconds else "scheduled",
                    dispatcher=dispatcher,
                    advance_schedule=True,
                    advance_from_now=late_seconds > current.misfire_grace_seconds,
                )
                if occurrence.status is OccurrenceStatus.ENQUEUED:
                    enqueued.append(occurrence)
                else:
                    skipped.append(occurrence)
            finally:
                self.repository.release_lease(scope=scope, lease=lease)
        return SchedulerTickResult(
            now=now.isoformat(),
            enqueued=tuple(enqueued),
            skipped=tuple(skipped),
            recovered=tuple(recovered),
            notified=tuple(notified),
            lease_contention=contention,
        )

    def state(self, *, scope: TaskScope) -> dict[str, object]:
        schedules = self.list(scope=scope)
        occurrences = self.repository.list_occurrences(scope)
        notifications = self.repository.list_notifications(scope)
        return {
            "schema_version": "klara.scheduler-state.v1",
            "schedules": [item.to_public_dict() for item in schedules],
            "occurrences": [item.to_public_dict() for item in occurrences],
            "notifications": [item.to_public_dict() for item in notifications],
        }

    def mark_notification_read(
        self, *, scope: TaskScope, notification_id: str
    ) -> ScheduleNotification:
        result = self.repository.mark_notification_read(
            scope, notification_id, self._now()
        )
        if result is None:
            raise ScheduleNotFoundError("schedule_notification_not_found")
        return result

    def _materialize(
        self,
        schedule: Schedule,
        *,
        scheduled_for: datetime,
        trigger: str,
        dispatcher: DispatchCallback | None,
        advance_schedule: bool,
        advance_from_now: bool = False,
    ) -> ScheduleOccurrence:
        active = self._active_occurrences(schedule.scope, schedule.schedule_id)
        if active:
            result = (
                "overlap_queued_once"
                if schedule.overlap_policy is OverlapPolicy.QUEUE_ONE
                else "overlap_skipped"
            )
            occurrence = self._skip(
                schedule,
                scheduled_for=scheduled_for,
                status=OccurrenceStatus.SKIPPED_OVERLAP,
                result=result,
            )
            if schedule.overlap_policy is OverlapPolicy.QUEUE_ONE and not schedule.queued_overlap:
                schedule = self._save(schedule, queued_overlap=True)
            if advance_schedule:
                self._advance(
                    schedule,
                    scheduled_for=scheduled_for,
                    now=self._now_dt(),
                    catch_up=False,
                    occurrence_id=occurrence.occurrence_id,
                )
            return occurrence
        occurrence_id = _occurrence_id(schedule.schedule_id, scheduled_for, trigger)
        task_id = _task_id(occurrence_id)
        now = self._now()
        reserved = ScheduleOccurrence(
            occurrence_id=occurrence_id,
            schedule_id=schedule.schedule_id,
            task_id=task_id,
            scheduled_for=scheduled_for.isoformat(),
            status=OccurrenceStatus.RESERVED,
            trigger=trigger,
            created_at=now,
            updated_at=now,
        )
        occurrence, created = self.repository.reserve_occurrence(schedule.scope, reserved)
        if created or occurrence.status is OccurrenceStatus.RESERVED:
            occurrence = self._enqueue_reserved(schedule, occurrence, dispatcher)
        if advance_schedule:
            self._advance(
                schedule,
                scheduled_for=scheduled_for,
                now=self._now_dt(),
                catch_up=not advance_from_now,
                occurrence_id=occurrence.occurrence_id,
            )
        return occurrence

    def _enqueue_reserved(
        self,
        schedule: Schedule,
        occurrence: ScheduleOccurrence,
        dispatcher: DispatchCallback | None,
    ) -> ScheduleOccurrence:
        if occurrence.task_id is None:
            raise RuntimeError("reserved_occurrence_requires_task_id")
        try:
            self.task_service.get(scope=schedule.scope, task_id=occurrence.task_id)
        except TaskNotFoundError:
            self.task_service.create(
                scope=schedule.scope,
                task_id=occurrence.task_id,
                title=schedule.title,
                description=schedule.task_description,
                max_attempts=3,
            )
        enqueued = replace(
            occurrence,
            status=OccurrenceStatus.ENQUEUED,
            updated_at=self._now(),
            result="queued",
        )
        self.repository.save_occurrence(schedule.scope, enqueued)
        if dispatcher is not None:
            dispatcher(schedule, enqueued)
        return enqueued

    def _recover_reserved(
        self, scope: TaskScope, *, dispatcher: DispatchCallback | None
    ) -> list[ScheduleOccurrence]:
        recovered: list[ScheduleOccurrence] = []
        for occurrence in self.repository.list_pending_occurrences(scope):
            schedule = self.get(scope=scope, schedule_id=occurrence.schedule_id)
            recovered.append(self._enqueue_reserved(schedule, occurrence, dispatcher))
        if dispatcher is not None:
            for occurrence in self.repository.list_occurrences(scope):
                if (
                    occurrence.status is not OccurrenceStatus.ENQUEUED
                    or occurrence.task_id is None
                ):
                    continue
                try:
                    task = self.task_service.get(
                        scope=scope, task_id=occurrence.task_id
                    )
                except TaskNotFoundError:
                    continue
                if task.state in {
                    TaskState.COMPLETED,
                    TaskState.FAILED,
                    TaskState.CANCELLED,
                }:
                    continue
                schedule = self.get(scope=scope, schedule_id=occurrence.schedule_id)
                dispatcher(schedule, occurrence)
                if occurrence not in recovered:
                    recovered.append(occurrence)
        return recovered

    def _sync_terminals(
        self,
        scope: TaskScope,
        *,
        dispatcher: DispatchCallback | None,
        notifier: NotificationCallback | None,
    ) -> list[ScheduleNotification]:
        notifications: list[ScheduleNotification] = []
        for occurrence in self.repository.list_occurrences(scope):
            if occurrence.status is not OccurrenceStatus.ENQUEUED or occurrence.task_id is None:
                continue
            try:
                task = self.task_service.get(scope=scope, task_id=occurrence.task_id)
            except TaskNotFoundError:
                continue
            mapping = {
                TaskState.COMPLETED: OccurrenceStatus.COMPLETED,
                TaskState.FAILED: OccurrenceStatus.FAILED,
                TaskState.CANCELLED: OccurrenceStatus.CANCELLED,
            }
            status = mapping.get(task.state)
            if status is None:
                continue
            now = self._now()
            result = status.value
            updated = replace(
                occurrence,
                status=status,
                result=result,
                updated_at=now,
                completed_at=now,
            )
            self.repository.save_occurrence(scope, updated)
        # Reconcile all terminal occurrences, including one persisted immediately
        # before a process death. Deterministic notification IDs make this replay
        # safe even when this loop is entered repeatedly.
        latest_schedule_ids: set[str] = set()
        for occurrence in self.repository.list_occurrences(scope):
            if occurrence.status not in {
                OccurrenceStatus.COMPLETED,
                OccurrenceStatus.FAILED,
                OccurrenceStatus.CANCELLED,
            } or occurrence.task_id is None:
                continue
            result = occurrence.result or occurrence.status.value
            schedule = self.get(scope=scope, schedule_id=occurrence.schedule_id)
            is_latest = schedule.schedule_id not in latest_schedule_ids
            latest_schedule_ids.add(schedule.schedule_id)
            if is_latest and (
                schedule.last_occurrence_id != occurrence.occurrence_id
                or schedule.last_result != result
            ):
                schedule = self._save(
                    schedule,
                    last_occurrence_id=occurrence.occurrence_id,
                    last_result=result,
                )
            notification = ScheduleNotification(
                notification_id=_notification_id(occurrence.occurrence_id, result),
                schedule_id=schedule.schedule_id,
                occurrence_id=occurrence.occurrence_id,
                task_id=occurrence.task_id,
                session_id=schedule.session_id,
                result=result,
                title=schedule.title,
                message=f'Scheduled task "{schedule.title}" {result}.',
                created_at=occurrence.completed_at or occurrence.updated_at,
            )
            self.repository.save_notification(scope, notification)
            if (
                is_latest
                and schedule.queued_overlap
                and schedule.status is ScheduleStatus.ACTIVE
            ):
                schedule = self._save(schedule, queued_overlap=False)
                self.run_now(
                    scope=scope,
                    schedule_id=schedule.schedule_id,
                    dispatcher=dispatcher,
                )
        # Notification creation and delivery are separate durable steps. A process
        # death after the insert therefore replays delivery, while a deterministic
        # message identifier keeps the chat projection idempotent.
        for notification in self.repository.list_pending_notifications(scope):
            if notifier is not None:
                notifier(notification)
                delivered = self.repository.mark_notification_delivered(
                    scope, notification.notification_id, self._now()
                )
                notifications.append(delivered or notification)
        return notifications

    def _active_occurrences(
        self, scope: TaskScope, schedule_id: str
    ) -> list[ScheduleOccurrence]:
        active: list[ScheduleOccurrence] = []
        for occurrence in self.repository.list_occurrences(scope, schedule_id):
            if occurrence.status is not OccurrenceStatus.ENQUEUED or not occurrence.task_id:
                continue
            try:
                state = self.task_service.get(
                    scope=scope, task_id=occurrence.task_id
                ).state
            except TaskNotFoundError:
                continue
            if state not in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
                active.append(occurrence)
        return active

    def _skip(
        self,
        schedule: Schedule,
        *,
        scheduled_for: datetime,
        status: OccurrenceStatus,
        result: str,
    ) -> ScheduleOccurrence:
        now = self._now()
        occurrence = ScheduleOccurrence(
            occurrence_id=_occurrence_id(schedule.schedule_id, scheduled_for, status.value),
            schedule_id=schedule.schedule_id,
            task_id=None,
            scheduled_for=scheduled_for.isoformat(),
            status=status,
            trigger=status.value,
            result=result,
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
        return self.repository.reserve_occurrence(schedule.scope, occurrence)[0]

    def _advance(
        self,
        schedule: Schedule,
        *,
        scheduled_for: datetime,
        now: datetime,
        catch_up: bool,
        occurrence_id: str,
    ) -> Schedule:
        if schedule.kind is ScheduleKind.ONCE:
            return self._save(
                schedule,
                status=ScheduleStatus.COMPLETED,
                next_run_at=None,
                last_scheduled_at=scheduled_for.isoformat(),
                last_occurrence_id=occurrence_id,
            )
        after = scheduled_for if catch_up else now
        next_run = _next_after(schedule, after)
        return self._save(
            schedule,
            next_run_at=next_run.isoformat() if next_run else None,
            last_scheduled_at=scheduled_for.isoformat(),
            last_occurrence_id=occurrence_id,
        )

    def _save(self, schedule: Schedule, **changes: object) -> Schedule:
        now = self._now_dt()
        prior = _aware_utc(schedule.updated_at)
        updated_at = max(now, prior + timedelta(microseconds=1)).isoformat()
        updated = replace(schedule, updated_at=updated_at, **changes)
        self.repository.save_schedule(updated, prior_updated_at=schedule.updated_at)
        return updated

    def _now_dt(self) -> datetime:
        value = self._now_fn()
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    def _now(self) -> str:
        return self._now_dt().isoformat()


def _first_run(schedule: Schedule, *, now: datetime) -> datetime | None:
    if schedule.kind is ScheduleKind.ONCE:
        return _aware_utc(schedule.run_at or "")
    if schedule.kind is ScheduleKind.INTERVAL:
        if schedule.run_at:
            anchor = _aware_utc(schedule.run_at)
            if anchor > now:
                return anchor
            seconds = schedule.interval_seconds or 60
            steps = int((now - anchor).total_seconds() // seconds) + 1
            return anchor + timedelta(seconds=steps * seconds)
        return now + timedelta(seconds=schedule.interval_seconds or 60)
    return _next_local(schedule, after=now - timedelta(microseconds=1))


def _next_after(schedule: Schedule, after: datetime) -> datetime | None:
    if schedule.kind is ScheduleKind.INTERVAL:
        return after + timedelta(seconds=schedule.interval_seconds or 60)
    if schedule.kind in {ScheduleKind.DAILY, ScheduleKind.WEEKLY}:
        return _next_local(schedule, after=after)
    return None


def _next_local(schedule: Schedule, *, after: datetime) -> datetime | None:
    zone = _zone(schedule.timezone)
    clock = _local_clock(schedule.local_time)
    local_after = after.astimezone(zone)
    for day_offset in range(SchedulerService.MAX_HORIZON_DAYS + 1):
        candidate_date = local_after.date() + timedelta(days=day_offset)
        if schedule.kind is ScheduleKind.WEEKLY and candidate_date.weekday() not in schedule.weekdays:
            continue
        naive = datetime.combine(candidate_date, clock)
        instants = _local_instants(naive, zone)
        if not instants:
            # Spring-forward gaps move to the first valid local minute after the gap.
            for minute in range(1, 181):
                instants = _local_instants(naive + timedelta(minutes=minute), zone)
                if instants:
                    break
        # A civil daily/weekly schedule fires once on a fall-back day. We choose
        # the earlier fold deterministically instead of firing the repeated wall
        # clock time twice.
        for instant in instants[:1]:
            if instant > after:
                return instant
    return None


def _local_instants(naive: datetime, zone: ZoneInfo) -> list[datetime]:
    values: list[datetime] = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        utc_value = aware.astimezone(UTC)
        if utc_value.astimezone(zone).replace(tzinfo=None) == naive and utc_value not in values:
            values.append(utc_value)
    return sorted(values)


def _zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value.strip())
    except (ZoneInfoNotFoundError, ValueError):
        raise ScheduleValidationError("schedule_timezone_invalid") from None


def _local_clock(value: str | None) -> time:
    try:
        parsed = time.fromisoformat(value or "")
    except ValueError:
        raise ScheduleValidationError("schedule_local_time_invalid") from None
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise ScheduleValidationError("schedule_local_time_requires_HH_MM")
    return parsed


def _aware_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ScheduleValidationError("schedule_datetime_invalid") from None
    if parsed.tzinfo is None:
        raise ScheduleValidationError("schedule_datetime_requires_timezone")
    return parsed.astimezone(UTC)


def _occurrence_id(schedule_id: str, scheduled_for: datetime, trigger: str) -> str:
    payload = f"{schedule_id}|{scheduled_for.astimezone(UTC).isoformat()}|{trigger}"
    return f"occurrence_{hashlib.sha256(payload.encode()).hexdigest()[:32]}"


def _task_id(occurrence_id: str) -> str:
    return f"task_occ_{hashlib.sha256(occurrence_id.encode()).hexdigest()[:24]}"


def _notification_id(occurrence_id: str, result: str) -> str:
    payload = f"{occurrence_id}|{result}"
    return f"notification_{hashlib.sha256(payload.encode()).hexdigest()[:32]}"
