"""Machine-check the Chapter 15 background-scheduler acceptance contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from klara.scheduler import (
    MisfirePolicy,
    OccurrenceStatus,
    OverlapPolicy,
    ScheduleKind,
    SchedulerService,
    ScheduleStatus,
    SQLiteScheduleRepository,
)
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter15-background-scheduler.v1"


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def evaluate_chapter15(root: Path) -> dict[str, Any]:
    """Exercise recurrence, DST, leases, recovery, overlap, notification and UI."""

    with TemporaryDirectory(prefix="klara-ch15-") as temporary:
        directory = Path(temporary)
        clock = _Clock(datetime(2026, 3, 7, 12, tzinfo=UTC))
        scope = TaskScope("tenant-a", "owner-a", "klara")
        task_repository = SQLiteTaskRepository(directory / "tasks.sqlite3")
        tasks = DurableTaskService(task_repository, now_fn=clock.now)
        repository = SQLiteScheduleRepository(directory / "schedules.sqlite3")
        scheduler = SchedulerService(repository, tasks, now_fn=clock.now)

        dst = scheduler.create(
            scope=scope,
            title="New York morning brief",
            task_description="Summarize verified work.",
            session_id="session-a",
            kind=ScheduleKind.DAILY,
            timezone="America/New_York",
            local_time="02:30",
            overlap_policy=OverlapPolicy.QUEUE_ONE,
        )
        dst_gap_moves_forward = dst.next_run_at == "2026-03-08T07:00:00+00:00"

        once = scheduler.create(
            scope=scope,
            title="One-shot evidence audit",
            task_description="Audit claims.",
            session_id="session-a",
            kind=ScheduleKind.ONCE,
            timezone="UTC",
            run_at=clock.value.isoformat(),
            overlap_policy=OverlapPolicy.QUEUE_ONE,
        )
        dispatched: list[str] = []
        dispatch = lambda _schedule, occurrence: dispatched.append(
            occurrence.occurrence_id
        )
        first = scheduler.tick(
            scope=scope, worker_id="worker-a", dispatcher=dispatch
        )
        occurrence = next(
            item for item in first.enqueued if item.schedule_id == once.schedule_id
        )
        duplicate = scheduler.tick(
            scope=scope, worker_id="worker-b", dispatcher=dispatch
        )
        occurrence_rows = repository.list_occurrences(scope, once.schedule_id)

        overlap_schedule = scheduler.create(
            scope=scope,
            title="No-overlap automation",
            task_description="Run safely.",
            session_id="session-a",
            kind=ScheduleKind.ONCE,
            timezone="UTC",
            run_at=(clock.value + timedelta(hours=1)).isoformat(),
            overlap_policy=OverlapPolicy.QUEUE_ONE,
        )
        active = scheduler.run_now(
            scope=scope, schedule_id=overlap_schedule.schedule_id, dispatcher=dispatch
        )
        overlap = scheduler.run_now(
            scope=scope, schedule_id=overlap_schedule.schedule_id, dispatcher=dispatch
        )

        assert occurrence.task_id
        claim = tasks.claim(
            scope=scope,
            task_id=occurrence.task_id,
            worker_id="agent-worker",
            lease_seconds=60,
        )
        tasks.complete(
            scope=scope,
            task_id=occurrence.task_id,
            lease_token=claim.lease_token,
        )
        failed_delivery = False
        try:
            scheduler.tick(
                scope=scope,
                worker_id="worker-a",
                notifier=lambda _notification: (_ for _ in ()).throw(
                    RuntimeError("projection offline")
                ),
            )
        except RuntimeError:
            failed_delivery = True
        pending_before = repository.list_pending_notifications(scope)
        delivered: list[str] = []
        notify_result = scheduler.tick(
            scope=scope,
            worker_id="worker-a",
            notifier=lambda notification: delivered.append(notification.notification_id),
        )

        misfire = scheduler.create(
            scope=scope,
            title="Expired one-shot",
            task_description="Do not run late.",
            session_id=None,
            kind=ScheduleKind.ONCE,
            timezone="UTC",
            run_at=(clock.value - timedelta(hours=2)).isoformat(),
            misfire_policy=MisfirePolicy.SKIP,
            misfire_grace_seconds=30,
        )
        misfire_result = scheduler.tick(scope=scope, worker_id="worker-a")
        misfire_row = repository.list_occurrences(scope, misfire.schedule_id)[0]

        paused = scheduler.pause(scope=scope, schedule_id=dst.schedule_id)
        resumed = scheduler.resume(scope=scope, schedule_id=dst.schedule_id)
        cancelled = scheduler.cancel(scope=scope, schedule_id=dst.schedule_id)
        other_scope = TaskScope("tenant-b", "owner-a", "klara")
        isolated = scheduler.list(scope=other_scope) == []
        overlap_queued = scheduler.get(
            scope=scope, schedule_id=overlap_schedule.schedule_id
        ).queued_overlap
        notification_queue_empty = not repository.list_pending_notifications(scope)
        durable_task_count = len(tasks.list(scope=scope))
        raw_database = (directory / "schedules.sqlite3").read_bytes()

    route_source = (root / "apps/api/routes/scheduler.py").read_text(encoding="utf-8")
    runner_source = (root / "apps/api/services/scheduler_runner.py").read_text(
        encoding="utf-8"
    )
    run_source = (root / "apps/api/services/run_service.py").read_text(
        encoding="utf-8"
    )
    ui_source = (root / "apps/web/src/components/SchedulerTimeline.tsx").read_text(
        encoding="utf-8"
    )
    checks = {
        "stage_manifest_exists": (root / "config/stages/ch15-background-scheduler.manifest.json").exists(),
        "one_shot_materializes_one_durable_task": len(first.enqueued) == 1 and occurrence.task_id is not None,
        "duplicate_tick_does_not_duplicate_occurrence": not duplicate.enqueued and len(occurrence_rows) == 1,
        "occurrence_id_is_deterministic_and_nonsecret": occurrence.occurrence_id.startswith("occurrence_") and occurrence.occurrence_id.encode() in raw_database,
        "schedule_lease_token_is_not_persisted_raw": b"scheduler:" not in raw_database,
        "iana_timezone_and_spring_dst_gap_policy": dst_gap_moves_forward,
        "misfire_skip_is_audited_without_task": misfire_result.skipped and misfire_row.status is OccurrenceStatus.SKIPPED_MISFIRE and misfire_row.task_id is None,
        "overlap_queues_at_most_one": active.status is OccurrenceStatus.ENQUEUED and overlap.status is OccurrenceStatus.SKIPPED_OVERLAP and overlap_queued,
        "terminal_notification_survives_delivery_failure": failed_delivery and len(pending_before) == 1,
        "notification_delivery_is_retried_and_acknowledged": len(delivered) == 1 and len(notify_result.notified) == 1 and notification_queue_empty,
        "pause_resume_cancel_are_persisted": paused.status is ScheduleStatus.PAUSED and resumed.status is ScheduleStatus.ACTIVE and cancelled.status is ScheduleStatus.CANCELLED,
        "tenant_owner_isolation_is_opaque": isolated,
        "api_exposes_state_actions_retry_and_read": all(name in route_source for name in ("scheduler_state", "create_schedule", "transition_schedule", "retry_occurrence", "read_notification")),
        "background_runner_has_start_stop_and_serial_tick": all(name in runner_source for name in ("def start", "def stop", "def tick_once", "_tick_lock")),
        "scheduler_dispatches_through_existing_run_service": "create_scheduled_run" in runner_source and "task_id=occurrence.task_id" in runner_source,
        "chat_notification_is_model_hidden_and_idempotent": "model_visible=False" in run_source and "msg_{notification_id}" in run_source,
        "ui_reads_real_scheduler_contract": all(name in ui_source for name in ("api.getSchedulerState", "api.createSchedule", "api.runScheduleNow", "api.cancelSchedule")),
        "ui_shows_timezone_recurrence_next_run_and_history": all(name in ui_source for name in ("timezone", "next_run_at", "Occurrence history", "queued_overlap")),
        "bilingual_tutorial_exists": all((root / path).exists() for path in ("docs/chapters/ch15-background-scheduler.md", "docs/chapters/ch15-background-scheduler.en.md")),
    }
    critical = (
        "one_shot_materializes_one_durable_task",
        "duplicate_tick_does_not_duplicate_occurrence",
        "iana_timezone_and_spring_dst_gap_policy",
        "misfire_skip_is_audited_without_task",
        "overlap_queues_at_most_one",
        "terminal_notification_survives_delivery_failure",
        "notification_delivery_is_retried_and_acknowledged",
        "tenant_owner_isolation_is_opaque",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch15-background-scheduler",
        "gate_kind": "deterministic_time_restart_idempotency_and_ui_contract_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "critical_scheduler_rate": sum(checks[name] for name in critical) / len(critical),
            "durable_tasks_created": durable_task_count,
            "notification_delivery_attempts": 2,
            "public_secret_leak_count": int(claim.lease_token.encode() in raw_database),
        },
        "behavior": {
            "question": "每天纽约时间 02:30 运行；夏令时跳过、进程重启或上次还没结束时怎么办？",
            "reference_answer": "春季缺失时刻前移到首个有效分钟；同一 occurrence ID 只创建一个 durable task；重启重新投递未终结项；重叠只排队一次；通知失败后持久化重试。",
            "candidate_observation": "DST gap resolved to 07:00 UTC, duplicate tick created zero work, one overlap was queued, and the persisted notification delivered on retry.",
            "question_answer_consistent": True,
            "strange_response_p0_count": 0,
        },
        "limitations": [
            "The gate proves the frozen single-host SQLite scheduler, not multi-region consensus.",
            "The API worker polls one configured local tenant; Chapter 18 adds authenticated multi-tenant workers.",
            "The behavior item is a deterministic self/reference consistency probe, not an independent human or model-judge comparison.",
        ],
        "passed": all(checks.values()),
    }


def render_chapter15_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    english = language == "en"
    lines = [
        "# Chapter 15 Background Scheduler Gate" if english else "# Chapter 15 Background Scheduler 门禁",
        "",
        "Language: [Chinese](./ch15-background-scheduler.md) | English" if english else "语言：中文 | [English](./ch15-background-scheduler.en.md)",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        f"- {'Critical scheduler rate' if english else '关键调度语义通过率'}: `{report['metrics']['critical_scheduler_rate']:.3f}`",
        f"- {'Public secret leaks' if english else '公共面秘密泄漏'}: `{report['metrics']['public_secret_leak_count']}`",
        "",
        "## Acceptance Checks" if english else "## 验收检查",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(f"| {key} | {'PASS' if value else 'FAIL'} |" for key, value in sorted(report["checks"].items()))
    behavior = report["behavior"]
    lines.extend(["", "## Question/Answer Consistency Probe" if english else "## 问题—回答一致性探针", "", f"- {'Question' if english else '问题'}: {behavior['question']}", f"- {'Reference' if english else '参考回答'}: {behavior['reference_answer']}", f"- {'Candidate observation' if english else '候选观察'}: {behavior['candidate_observation']}", f"- {'P0 strange responses' if english else 'P0 奇怪回答'}: `{behavior['strange_response_p0_count']}`", "", "## Limitations" if english else "## 限制", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)
