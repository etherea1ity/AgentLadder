"""Typed schedule, occurrence, and notification contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from klara.tasks import TaskScope


class ScheduleKind(StrEnum):
    ONCE = "once"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"


class ScheduleStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MisfirePolicy(StrEnum):
    FIRE_ONCE = "fire_once"
    SKIP = "skip"


class OverlapPolicy(StrEnum):
    SKIP = "skip"
    QUEUE_ONE = "queue_one"


class OccurrenceStatus(StrEnum):
    RESERVED = "reserved"
    ENQUEUED = "enqueued"
    SKIPPED_MISFIRE = "skipped_misfire"
    SKIPPED_OVERLAP = "skipped_overlap"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    scope: TaskScope
    title: str
    task_description: str
    session_id: str | None
    kind: ScheduleKind
    timezone: str
    status: ScheduleStatus
    run_at: str | None = None
    local_time: str | None = None
    weekdays: tuple[int, ...] = ()
    interval_seconds: int | None = None
    misfire_policy: MisfirePolicy = MisfirePolicy.FIRE_ONCE
    misfire_grace_seconds: int = 300
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP
    next_run_at: str | None = None
    last_scheduled_at: str | None = None
    last_occurrence_id: str | None = None
    last_result: str | None = None
    queued_overlap: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope"] = self.scope.to_public_dict()
        for key in ("kind", "status", "misfire_policy", "overlap_policy"):
            value[key] = getattr(self, key).value
        return value


@dataclass(frozen=True)
class ScheduleOccurrence:
    occurrence_id: str
    schedule_id: str
    task_id: str | None
    scheduled_for: str
    status: OccurrenceStatus
    trigger: str
    created_at: str
    updated_at: str
    completed_at: str | None = None
    result: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


@dataclass(frozen=True)
class ScheduleNotification:
    notification_id: str
    schedule_id: str
    occurrence_id: str
    task_id: str
    session_id: str | None
    result: str
    title: str
    message: str
    created_at: str
    read_at: str | None = None
    delivered_at: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SchedulerLease:
    schedule_id: str
    worker_id: str
    token: str
    expires_at: str


@dataclass(frozen=True)
class SchedulerTickResult:
    now: str
    enqueued: tuple[ScheduleOccurrence, ...] = ()
    skipped: tuple[ScheduleOccurrence, ...] = ()
    recovered: tuple[ScheduleOccurrence, ...] = ()
    notified: tuple[ScheduleNotification, ...] = ()
    lease_contention: int = 0

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "klara.scheduler-tick.v1",
            "now": self.now,
            "enqueued": [item.to_public_dict() for item in self.enqueued],
            "skipped": [item.to_public_dict() for item in self.skipped],
            "recovered": [item.to_public_dict() for item in self.recovered],
            "notified": [item.to_public_dict() for item in self.notified],
            "lease_contention": self.lease_contention,
        }


def new_schedule_id() -> str:
    return f"schedule_{uuid4().hex}"


def new_notification_id() -> str:
    return f"notification_{uuid4().hex}"
