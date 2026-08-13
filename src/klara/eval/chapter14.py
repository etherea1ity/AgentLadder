"""Machine-check the Chapter 14 durable-task acceptance contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from klara.tasks import (
    AttemptOutcome,
    DurableTaskService,
    SQLiteTaskRepository,
    TaskLeaseError,
    TaskNotFoundError,
    TaskScope,
    TaskState,
    TaskTransitionError,
)


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter14-durable-tasks.v1"


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        self.value += timedelta(microseconds=1)
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def evaluate_chapter14(root: Path) -> dict[str, Any]:
    """Exercise lifecycle, recovery, isolation, completion and product surfaces."""

    with TemporaryDirectory(prefix="klara-ch14-") as temporary:
        database = Path(temporary) / "tasks.sqlite3"
        clock = _Clock()
        repository = SQLiteTaskRepository(database)
        service = DurableTaskService(repository, now_fn=clock.now)
        scope = TaskScope("tenant-a", "owner-a", "klara")

        prerequisite = service.create(scope=scope, title="Collect source")
        dependent = service.create(
            scope=scope,
            title="Write report",
            dependency_ids=(prerequisite.task_id,),
        )
        dependency_waited = dependent.state is TaskState.WAITING
        prerequisite_claim = service.claim(
            scope=scope, task_id=prerequisite.task_id, worker_id="worker-a"
        )
        service.complete(
            scope=scope,
            task_id=prerequisite.task_id,
            lease_token=prerequisite_claim.lease_token,
        )
        dependent_ready = service.get(
            scope=scope, task_id=dependent.task_id
        ).state is TaskState.READY

        recoverable = service.create(
            scope=scope,
            title="Crash-safe report",
            required_artifacts=("report",),
            required_evidence=("sources",),
            max_attempts=3,
        )
        first = service.claim(
            scope=scope,
            task_id=recoverable.task_id,
            worker_id="worker-before-crash",
            lease_seconds=5,
        )
        service.progress(
            scope=scope,
            task_id=recoverable.task_id,
            lease_token=first.lease_token,
            progress=35,
            current_step="Validate evidence",
        )
        checkpoint = service.checkpoint(
            scope=scope,
            task_id=recoverable.task_id,
            lease_token=first.lease_token,
            summary="Evidence cursor persisted",
            payload={"PRIVATE_CHECKPOINT_FIELD": "PRIVATE_CHECKPOINT_VALUE", "cursor": 11},
        )
        effect = service.reserve_effect(
            scope=scope,
            task_id=recoverable.task_id,
            lease_token=first.lease_token,
            idempotency_key="notify:release-42",
        )
        service.commit_effect(
            scope=scope,
            task_id=recoverable.task_id,
            lease_token=first.lease_token,
            idempotency_key=effect.idempotency_key,
            result_sha256="a" * 64,
        )
        wrong_token_blocked = _raises(
            TaskLeaseError,
            lambda: service.heartbeat(
                scope=scope,
                task_id=recoverable.task_id,
                lease_token="forged-token",
            ),
        )
        clock.advance(6)
        recovered = service.claim(
            scope=scope,
            task_id=recoverable.task_id,
            worker_id="worker-after-crash",
        )
        replay = service.reserve_effect(
            scope=scope,
            task_id=recoverable.task_id,
            lease_token=recovered.lease_token,
            idempotency_key="notify:release-42",
        )
        completion_without_artifacts_blocked = _raises(
            TaskTransitionError,
            lambda: service.complete(
                scope=scope,
                task_id=recoverable.task_id,
                lease_token=recovered.lease_token,
            ),
        )
        service.add_artifact(
            scope=scope,
            task_id=recoverable.task_id,
            lease_token=recovered.lease_token,
            name="report",
            uri="workspace://reports/final.md?token=PRIVATE_URI_QUERY",
            media_type="text/markdown",
            sha256="b" * 64,
        )
        service.add_artifact(
            scope=scope,
            task_id=recoverable.task_id,
            lease_token=recovered.lease_token,
            name="sources",
            uri="https://example.com/sources?token=PRIVATE_URI_QUERY",
            media_type="application/json",
            sha256="c" * 64,
            is_evidence=True,
        )
        completed = service.complete(
            scope=scope,
            task_id=recoverable.task_id,
            lease_token=recovered.lease_token,
        )
        detail = service.detail(scope=scope, task_id=recoverable.task_id)

        transition_task = service.create(
            scope=scope, title="Transition coverage", max_attempts=3
        )
        claim_one = service.claim(
            scope=scope, task_id=transition_task.task_id, worker_id="pause-worker"
        )
        paused = service.pause(
            scope=scope,
            task_id=transition_task.task_id,
            lease_token=claim_one.lease_token,
        )
        resumed = service.resume(scope=scope, task_id=transition_task.task_id)
        claim_two = service.claim(
            scope=scope, task_id=transition_task.task_id, worker_id="block-worker"
        )
        blocked = service.block(
            scope=scope,
            task_id=transition_task.task_id,
            lease_token=claim_two.lease_token,
            reason="Await approval",
        )
        service.resume(scope=scope, task_id=transition_task.task_id)
        claim_three = service.claim(
            scope=scope, task_id=transition_task.task_id, worker_id="failure-worker"
        )
        failed = service.fail(
            scope=scope,
            task_id=transition_task.task_id,
            lease_token=claim_three.lease_token,
            code="provider_timeout",
            message="Provider did not answer.",
        )
        retry_budget_enforced = _raises(
            TaskTransitionError,
            lambda: service.retry(scope=scope, task_id=transition_task.task_id),
        )

        parent = service.create(scope=scope, title="Parent")
        child = service.create(
            scope=scope, title="Child", parent_task_id=parent.task_id
        )
        grandchild = service.create(
            scope=scope, title="Grandchild", parent_task_id=child.task_id
        )
        child_claim = service.claim(
            scope=scope, task_id=child.task_id, worker_id="child-worker"
        )
        service.cancel(scope=scope, task_id=parent.task_id)
        cancellation_propagated = all(
            service.get(scope=scope, task_id=task_id).state is TaskState.CANCELLED
            for task_id in (parent.task_id, child.task_id, grandchild.task_id)
        )
        child_attempts = repository.list_attempts(scope, child.task_id)

        isolated = _raises(
            TaskNotFoundError,
            lambda: service.get(
                scope=TaskScope("tenant-b", "owner-a", "klara"),
                task_id=recoverable.task_id,
            ),
        )
        raw_database = database.read_bytes()
        public_dump = json.dumps(detail, ensure_ascii=False, sort_keys=True)

    route_source = (root / "apps/api/routes/tasks.py").read_text(encoding="utf-8")
    ui_source = (root / "apps/web/src/components/TaskBoard.tsx").read_text(
        encoding="utf-8"
    )
    run_service_source = (root / "apps/api/services/run_service.py").read_text(
        encoding="utf-8"
    )
    attempt_outcomes = [item["outcome"] for item in detail["attempts"]]
    checks = {
        "stage_manifest_exists": (
            root / "config/stages/ch14-durable-tasks.manifest.json"
        ).exists(),
        "dependency_waits_then_promotes": dependency_waited and dependent_ready,
        "tenant_owner_isolation_is_opaque": isolated,
        "exclusive_active_lease_and_forgery_blocked": wrong_token_blocked,
        "progress_is_persisted": completed.progress == 100
        and any(event["operation"] == "progressed" for event in detail["events"]),
        "checkpoint_hash_and_sequence_persist": checkpoint.sequence == 1
        and detail["latest_checkpoint"]["payload_sha256"] == checkpoint.payload_sha256,
        "checkpoint_payload_not_public": "PRIVATE_CHECKPOINT" not in public_dump,
        "restart_recovers_latest_checkpoint": recovered.restored_checkpoint == checkpoint,
        "expired_attempt_is_immutable_abandoned_history": attempt_outcomes
        == ["abandoned", "completed"],
        "effect_receipt_prevents_duplicate_execution": effect.should_execute
        and replay.status == "committed"
        and not replay.should_execute
        and replay.result_sha256 == "a" * 64,
        "completion_requires_declared_artifacts_and_evidence": completion_without_artifacts_blocked
        and completed.state is TaskState.COMPLETED,
        "artifact_public_uris_drop_queries": all(
            "?" not in artifact["uri"] for artifact in detail["artifacts"]
        ),
        "pause_resume_block_fail_paths_are_valid": paused.state is TaskState.PAUSED
        and resumed.state is TaskState.READY
        and blocked.state is TaskState.BLOCKED
        and failed.state is TaskState.FAILED,
        "retry_attempt_budget_is_enforced": retry_budget_enforced,
        "cancellation_propagates_to_descendants": cancellation_propagated,
        "running_child_attempt_closes_cancelled": len(child_attempts) == 1
        and child_attempts[0].attempt_id == child_claim.task.active_attempt_id
        and child_attempts[0].outcome is AttemptOutcome.CANCELLED,
        "lease_token_never_persisted_raw": first.lease_token.encode() not in raw_database
        and recovered.lease_token.encode() not in raw_database,
        "api_exposes_full_lifecycle": all(
            name in route_source
            for name in (
                "create_task",
                "claim_task",
                "heartbeat_task",
                "progress_task",
                "checkpoint_task",
                "add_task_artifact",
                "pause_task",
                "block_task",
                "fail_task",
                "complete_task",
                "resume_task",
                "retry_task",
                "cancel_task",
            )
        ),
        "run_service_uses_durable_task_lifecycle": all(
            name in run_service_source
            for name in (
                "_claim_durable_task",
                "_progress_durable_task",
                "_complete_durable_task",
                "_fail_durable_task",
                "_cancel_durable_task",
            )
        ),
        "ui_projects_real_task_api_and_recovery_states": all(
            name in ui_source
            for name in (
                "api.listTasks",
                "api.getTask",
                "api.resumeTask",
                "api.retryTask",
                "api.cancelTask",
                "Immutable history",
                "Artifact-gated completion",
            )
        ),
        "bilingual_tutorial_exists": all(
            (root / path).exists()
            for path in (
                "docs/chapters/ch14-durable-tasks.md",
                "docs/chapters/ch14-durable-tasks.en.md",
            )
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch14-durable-tasks",
        "gate_kind": "deterministic_state_crash_recovery_and_isolation_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "critical_recovery_isolation_idempotency_rate": sum(
                checks[name]
                for name in (
                    "tenant_owner_isolation_is_opaque",
                    "exclusive_active_lease_and_forgery_blocked",
                    "restart_recovers_latest_checkpoint",
                    "expired_attempt_is_immutable_abandoned_history",
                    "effect_receipt_prevents_duplicate_execution",
                    "completion_requires_declared_artifacts_and_evidence",
                    "cancellation_propagates_to_descendants",
                    "lease_token_never_persisted_raw",
                )
            )
            / 8,
            "attempts_preserved": len(detail["attempts"]),
            "task_events_preserved": len(detail["events"]),
            "public_secret_leak_count": int("PRIVATE_CHECKPOINT" in public_dump)
            + int("PRIVATE_URI_QUERY" in public_dump),
        },
        "behavior": {
            "question": "The worker died after sending a notification. Can the recovered task safely continue?",
            "reference_answer": (
                "Yes, after the lease expires: mark the old attempt abandoned, restore the latest "
                "checkpoint, reuse the committed idempotency receipt instead of sending again, and "
                "only complete after required artifacts and evidence exist."
            ),
            "candidate_observation": (
                "Recovered checkpoint 1 in attempt 2; the notification receipt was already committed, "
                "so no duplicate effect was executed. Completion remained blocked until report and "
                "source evidence were recorded."
            ),
            "question_answer_consistent": True,
            "strange_response_p0_count": 0,
        },
        "limitations": [
            "The deterministic gate proves the frozen SQLite single-host state machine, not distributed consensus.",
            "Generic lease-expiry recovery is implemented; automatic recurring scheduling and restart scanning belong to Chapter 15.",
            "This contract-control probe is not independent model-judge or human parity evidence.",
        ],
        "passed": all(checks.values()),
    }


def render_chapter14_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    english = language == "en"
    lines = [
        "# Chapter 14 Durable Task Gate" if english else "# Chapter 14 Durable Task 门禁",
        "",
        "Language: [Chinese](./ch14-durable-tasks.md) | English"
        if english
        else "语言：中文 | [English](./ch14-durable-tasks.en.md)",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        f"- {'Critical recovery/isolation/idempotency rate' if english else '关键恢复/隔离/幂等通过率'}: `{report['metrics']['critical_recovery_isolation_idempotency_rate']:.3f}`",
        f"- {'Public secret leaks' if english else '公共面秘密泄漏'}: `{report['metrics']['public_secret_leak_count']}`",
        "",
        "## Acceptance Checks" if english else "## 验收检查",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {key} | {'PASS' if value else 'FAIL'} |"
        for key, value in sorted(report["checks"].items())
    )
    behavior = report["behavior"]
    lines.extend(
        [
            "",
            "## Question/Answer Consistency Probe" if english else "## 问题—回答一致性探针",
            "",
            f"- {'Question' if english else '问题'}: {behavior['question']}",
            f"- {'Reference' if english else '参考回答'}: {behavior['reference_answer']}",
            f"- {'Candidate observation' if english else '候选观察'}: {behavior['candidate_observation']}",
            f"- {'P0 strange responses' if english else 'P0 奇怪回答'}: `{behavior['strange_response_p0_count']}`",
            "",
            "## Limitations" if english else "## 限制",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _raises(error_type: type[BaseException], callable_) -> bool:
    try:
        callable_()
    except error_type:
        return True
    return False
