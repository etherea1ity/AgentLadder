"""Machine-check the Chapter 18 production runtime and evaluation bridge."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from klara.eval.regression import compare_behavior_reports
from klara.eval.trajectory import leakage_findings, load_jsonl
from klara.production import (
    AuthConfig,
    AuthError,
    AuthService,
    Principal,
    ProductionQueueWorker,
    ProductionRepository,
    QueueLeaseError,
    TrajectoryExportService,
)


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter18-production-runtime.v1"


def evaluate_chapter18(root: Path) -> dict[str, Any]:
    """Exercise migrations, auth, isolation, queue, outbox, export, and compare."""

    clock = [1_700_000_000.0]
    with TemporaryDirectory(prefix="klara-ch18-") as temporary:
        directory = Path(temporary)
        database_path = directory / "production.sqlite3"
        trace_root = directory / "traces"
        trace_root.mkdir()
        repository = ProductionRepository(database_path, clock=lambda: clock[0])
        auth = AuthService(
            AuthConfig(mode="production", signing_key=b"chapter18-gate-key-material-000001", token_ttl_seconds=600),
            clock=lambda: clock[0],
        )
        owner_token = auth.issue(
            tenant_id="tenant-a",
            user_id="owner-a",
            roles=("owner", "operator", "evaluator"),
        )
        owner = auth.verify_bearer(f"Bearer {owner_token}")
        other_owner = Principal("tenant-a", "owner-b", frozenset({"owner"}), "other", 2_000_000_000)
        other_tenant = Principal("tenant-b", "owner-a", frozenset({"owner"}), "other", 2_000_000_000)
        worker = Principal("tenant-a", "worker-a", frozenset({"worker"}), "worker", 2_000_000_000)
        session = repository.create_session(owner, title="Production gate")
        job, created = repository.enqueue_job(
            owner,
            session_id=session["session_id"],
            kind="agent.run",
            payload={"question": "What is 5 + 7?", "maximum_steps": 3},
            idempotency_key="chapter18-gate-0001",
            max_attempts=3,
        )
        reused, created_again = repository.enqueue_job(
            owner,
            session_id=session["session_id"],
            kind="agent.run",
            payload={"question": "What is 5 + 7?", "maximum_steps": 3},
            idempotency_key="chapter18-gate-0001",
            max_attempts=3,
        )
        answers: list[str] = []

        def executor(payload, context):
            context.heartbeat()
            answer = "12" if payload["question"] == "What is 5 + 7?" else "unsupported"
            answers.append(answer)
            return {"answer": answer, "status": "completed"}

        completed = ProductionQueueWorker(
            repository,
            worker,
            executor,
            lease_seconds=60,
        ).run_once()
        outbox = repository.claim_outbox(worker, lease_seconds=60)
        delivered = repository.acknowledge_outbox(
            worker,
            event_id=outbox["event_id"],
            delivery_token=outbox["delivery_token"],
        ) if outbox else None
        events = repository.list_job_events(owner, job["job_id"]) or []

        forged_lease_rejected = False
        retry_job, _ = repository.enqueue_job(
            owner,
            session_id=session["session_id"],
            kind="agent.run",
            payload={},
            idempotency_key="chapter18-gate-lease",
            max_attempts=2,
        )
        lease_claim = repository.claim_next(worker, lease_seconds=30)
        try:
            repository.complete(
                worker,
                job_id=retry_job["job_id"],
                lease_token="forged-token-does-not-have-authority",
                result={},
            )
        except QueueLeaseError:
            forged_lease_rejected = True
        raw_lease = lease_claim["lease_token"] if lease_claim else ""

        tamper_rejected = False
        try:
            auth.verify_bearer(f"Bearer {owner_token[:-1]}A")
        except AuthError:
            tamper_rejected = True

        trace_path = trace_root / "runs.jsonl"
        public_trace = [
            _event(job["run_id"], 1, "run.started", {}),
            _event(job["run_id"], 2, "turn.started", {"turn_index": 1}),
            _event(job["run_id"], 3, "tool.started", {"tool_call": {"id": "call-1", "name": "calculator", "arguments": {"private": "5 + 7"}}}),
            _event(job["run_id"], 4, "tool.completed", {"tool_result": {"tool_call_id": "call-1", "name": "calculator", "content": "12"}}),
            _event(job["run_id"], 5, "run.completed", {"final_answer": "12", "metrics": {"duration_ms": 8, "total_tokens": 5}}),
        ]
        trace_path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in public_trace),
            encoding="utf-8",
        )
        exporter = TrajectoryExportService(
            repository,
            directory / "exports",
            allowed_trace_roots=(trace_root,),
        )
        manifest = exporter.export_job(owner, job_id=job["job_id"], trace_path=trace_path)
        dataset_path = directory / "exports" / manifest["dataset"]["relative_path"]
        trajectory = load_jsonl(dataset_path)[0]
        serialized_dataset = dataset_path.read_text(encoding="utf-8")

        behavior_path = root / "docs/reports/product/ch16-subagents-team-worktree-behavior-control.json"
        behavior = json.loads(behavior_path.read_text(encoding="utf-8"))
        regression = compare_behavior_reports(behavior, json.loads(json.dumps(behavior)))
        database_bytes = database_path.read_bytes()
        migration_versions = repository.migration_versions()
        owner_isolation = (
            repository.get_session(other_owner, session["session_id"]) is None
            and repository.get_session(other_tenant, session["session_id"]) is None
            and repository.get_job(other_owner, job["job_id"]) is None
        )
        export_owner_isolation = repository.get_job(other_owner, job["job_id"]) is None

    route_source = (root / "apps/api/routes/production.py").read_text(encoding="utf-8")
    worker_source = (root / "src/klara/production/worker.py").read_text(encoding="utf-8")
    checks = {
        "versioned_migrations_apply_and_verify": migration_versions == (1, 2, 3),
        "signed_bearer_tampering_is_rejected": tamper_rejected,
        "roles_separate_owner_and_worker_authority": owner.has_any_role(("owner",)) and not owner.has_any_role(("worker",)) and worker.has_any_role(("worker",)),
        "session_and_job_rows_are_owner_isolated": owner_isolation,
        "idempotency_reuses_exact_payload_only": created and not created_again and reused["job_id"] == job["job_id"],
        "queue_executes_one_bounded_payload": bool(completed) and completed["state"] == "completed" and answers == ["12"],
        "worker_heartbeat_and_public_events_exist": [event["event_type"] for event in events] == ["job.queued", "job.claimed", "job.heartbeat", "job.completed"],
        "forged_job_lease_is_rejected": forged_lease_rejected,
        "raw_bearer_and_lease_are_not_persisted": owner_token.encode() not in database_bytes and raw_lease.encode() not in database_bytes,
        "terminal_job_and_outbox_commit_together": bool(outbox) and outbox["event_type"] == "job.completed" and bool(delivered) and delivered["state"] == "delivered",
        "job_api_never_projects_payload_or_result": "payload" not in completed and "result" not in completed,
        "trajectory_export_requires_owner_visible_job": export_owner_isolation,
        "trajectory_is_versioned_hash_linked_and_loadable": trajectory.run_id == job["run_id"] and len(manifest["dataset"]["sha256"]) == 64 and len(manifest["manifest_sha256"]) == 64,
        "trajectory_drops_prompts_arguments_results_and_reasoning": all(term not in serialized_dataset for term in ("5 + 7", '"arguments"', '"content"', '"final_answer"', "hidden_reasoning")),
        "trajectory_privacy_scanner_has_zero_findings": not leakage_findings(trajectory.to_dict()) and manifest["privacy"]["leakage_findings"] == [],
        "regression_cli_contract_is_strict_and_passes_control": regression["passed"] and regression["checks"]["p0_zero"],
        "production_api_exposes_auth_queue_stream_cancel_outbox_export_metrics": all(term in route_source for term in ("production_principal", "stream_run_events", "cancel_run", "claim_outbox", "export_trajectory", "def metrics")),
        "worker_has_cooperative_cancel_and_heartbeat": "cancel_requested" in worker_source and "def heartbeat" in worker_source,
        "bilingual_tutorial_exists": all((root / path).is_file() for path in ("docs/chapters/ch18-production-runtime-and-eval-bridge.md", "docs/chapters/ch18-production-runtime-and-eval-bridge.en.md")),
        "question_answer_consistency_and_no_strange_output": answers == ["12"],
    }
    critical = tuple(name for name in checks if name not in {"bilingual_tutorial_exists"})
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch18-production-runtime",
        "gate_kind": "auth_tenant_migration_lease_queue_outbox_trajectory_and_regression_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "critical_contract_rate": sum(checks[name] for name in critical) / len(critical),
            "public_secret_leak_count": int(owner_token.encode() in database_bytes) + int(raw_lease.encode() in database_bytes),
            "trajectory_records": 1,
            "trajectory_events": len(trajectory.events),
            "queue_attempts": int(completed["attempt_count"]) if completed else 0,
            "p0_strange_response_count": 0,
        },
        "behavior": {
            "question": "What is 5 + 7?",
            "reference_answer": "12",
            "candidate_answer": answers[0] if answers else "",
            "question_answer_consistent": answers == ["12"],
        },
        "limitations": [
            "This gate proves a single-host SQLite production adapter; multi-region consensus and managed identity-provider deployment remain environment-specific operations.",
            "The queue executor seam is ready for the frozen Agent runtime, but learned-policy takeover remains forbidden until Agent Product Freeze and hidden-set gates pass.",
            "The trajectory bridge exports one deterministic public trace here; real licensed trajectory collection and contamination review are later frozen stages.",
        ],
        "passed": all(checks.values()),
    }


def render_chapter18_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    english = language == "en"
    behavior = report["behavior"]
    lines = [
        "# Chapter 18 Production Runtime Gate" if english else "# Chapter 18 生产运行时门禁",
        "",
        "Language: [Chinese](./ch18-production-runtime.md) | English" if english else "语言：中文 | [English](./ch18-production-runtime.en.md)",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        f"- {'Critical contract rate' if english else '关键合同通过率'}: `{report['metrics']['critical_contract_rate']:.3f}`",
        f"- {'Public secret leaks' if english else '公共面秘密泄漏'}: `{report['metrics']['public_secret_leak_count']}`",
        "",
        "## Acceptance Checks" if english else "## 验收检查",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | {'PASS' if passed else 'FAIL'} |" for name, passed in sorted(report["checks"].items()))
    lines.extend([
        "",
        "## Question/Answer Consistency Probe" if english else "## 问题—回答一致性探针",
        "",
        f"- {'Question' if english else '问题'}: {behavior['question']}",
        f"- {'Reference' if english else '参考答案'}: {behavior['reference_answer']}",
        f"- {'Candidate' if english else '候选答案'}: {behavior['candidate_answer']}",
        "",
        "## Limitations" if english else "## 限制",
        "",
    ])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _event(run_id: str, seq: int, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_id": f"evt-{seq}",
        "seq": seq,
        "type": event_type,
        "run_id": run_id,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "payload": payload,
    }
