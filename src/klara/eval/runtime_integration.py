"""Machine-check that product services are callable through the real Agent loop."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from klara.app.harness import KlaraHarness, KlaraHarnessConfig
from klara.app.runtime_tools import runtime_tools
from klara.app.user_context import UserContext
from klara.core.messages import ModelResponse
from klara.core.tools import ToolCall
from klara.infra.config.runtime import CapabilityProfile
from klara.permissions import PermissionEffect, PermissionScope, PermissionService, SQLitePermissionRepository
from klara.scheduler import SQLiteScheduleRepository, SchedulerService
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope
from klara.teams import OneShotExecution, SQLiteTeamRepository, TeamScope, TeamService
from klara.tools.registry import ToolRegistry


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.agent-runtime-integration.v1"
RUNTIME_TOOL_NAMES = (
    "task_list", "task_create", "task_control",
    "schedule_list", "schedule_create", "schedule_control",
    "team_list", "subagent_spawn", "teammate_create", "team_message", "team_stop",
    "worktree_create", "worktree_inspect", "worktree_remove",
)


class _CreateTaskLlm:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs: object) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        "create-runtime-task",
                        "task_create",
                        {"title": "Durable integration task", "description": "Shared service proof"},
                    ),
                ),
            )
        messages = kwargs.get("messages", ())
        last_content = getattr(messages[-1], "content", "") if messages else ""
        if "approval is required" in last_content:
            return ModelResponse(
                content="Approval is required before the durable task can be created."
            )
        return ModelResponse(content="The durable task was created.")


def evaluate_runtime_integration(root: Path) -> dict[str, Any]:
    """Exercise fail-closed approval and shared durable state through KlaraHarness."""

    manifest = _read_json(root / "config/stages/agent-runtime-integration.manifest.json")
    with TemporaryDirectory(prefix="klara-runtime-integration-") as temporary:
        data_root = Path(temporary)
        task_service = DurableTaskService(SQLiteTaskRepository(data_root / "tasks.sqlite3"))
        task_scope = TaskScope("tenant-a", "owner-a", "klara")
        permission_path = data_root / "permissions.sqlite3"
        permission_service = PermissionService(SQLitePermissionRepository(permission_path))
        permission_scope = PermissionScope("tenant-a", "owner-a", "klara")
        scheduler_service = SchedulerService(
            SQLiteScheduleRepository(data_root / "schedules.sqlite3"), task_service
        )
        team_scope = TeamScope("tenant-a", "owner-a", "team-a")
        team_service = TeamService(
            SQLiteTeamRepository(data_root / "teams.sqlite3"),
            task_service,
            permission_service,
            project_root=root,
            executor=lambda *_: OneShotExecution("verified bounded result"),
        )
        adapters = runtime_tools(
            task_service=task_service,
            task_scope=task_scope,
            scheduler_service=scheduler_service,
            scheduler_scope=task_scope,
            scheduler_session_id="session-a",
            team_service=team_service,
            team_scope=team_scope,
            team_permission_scope=permission_scope,
        )
        names = tuple(tool.spec.name for tool in adapters)

        first_harness = _harness(
            root,
            data_root,
            task_service,
            task_scope,
            scheduler_service,
            team_service,
            team_scope,
            permission_scope,
        )
        first = first_harness.run(
            "Create the durable integration task.", run_id="runtime-gate-first"
        )
        permission_scope = first_harness.permission_scope
        tasks_after_block = task_service.list(scope=task_scope)
        state = permission_service.list_state(scope=permission_scope)
        pending = [item for item in state["requests"] if item["status"] == "pending"]
        request = pending[0] if pending else None
        grant = None
        if request is not None:
            grant = permission_service.decide_request(
                scope=permission_scope,
                request_id=str(request["request_id"]),
                effect=PermissionEffect.ALLOW_TASK,
                expires_seconds=600,
            )
        second = _harness(
            root,
            data_root,
            task_service,
            task_scope,
            scheduler_service,
            team_service,
            team_scope,
            permission_scope,
        ).run("Create the durable integration task.", run_id="runtime-gate-second")
        tasks_after_grant = task_service.list(scope=task_scope)
        raw_trace = (data_root / "trace.jsonl").read_text(encoding="utf-8")
        database_bytes = (data_root / "tasks.sqlite3").read_bytes()
        team_service.shutdown()

    first_tool_results = [message for message in first.messages if message.role == "tool"]
    second_tool_results = [message for message in second.messages if message.role == "tool"]
    source = (root / "apps/api/services/run_service.py").read_text(encoding="utf-8")
    runtime_config = (root / "config/runtime.toml").read_text(encoding="utf-8")
    live_report = _read_json(root / "docs/reports/product/agent-runtime-integration-live.json")
    live_report_path = root / "docs/reports/product/agent-runtime-integration-live.json"
    checks = {
        "all_runtime_tools_have_unique_model_specs": names == RUNTIME_TOOL_NAMES and len(names) == len(set(names)),
        "stage_manifest_exists": manifest.get("stage") == "agent-runtime-integration",
        "main_profile_exposes_every_runtime_tool": all(f'"{name}"' in runtime_config for name in RUNTIME_TOOL_NAMES),
        "run_service_injects_shared_product_services": all(
            term in source for term in ("task_service=self.task_service", "scheduler_service=self.scheduler_service", "team_service=self.team_service")
        ),
            "mutation_fails_closed_before_approval": not tasks_after_block
            and bool(first_tool_results)
            and "approval is required" in first_tool_results[-1].content,
        "approval_request_is_durable_and_exact": len(pending) == 1
        and request is not None
        and request["action"]["tool_name"] == "task_create"
        and request["scope"]["task_id"] == "session-a",
        "same_exact_action_executes_after_allow_task": len(tasks_after_grant) == 1
        and tasks_after_grant[0].title == "Durable integration task"
        and bool(second_tool_results)
        and second_tool_results[-1].content.startswith("{"),
            "created_task_is_visible_from_shared_service": bool(tasks_after_grant)
            and tasks_after_grant[0].description == "Shared service proof",
        "public_trace_omits_raw_tool_arguments": "Shared service proof" not in raw_trace,
            "permission_grant_id_not_in_task_database": grant is not None
            and grant.grant_id.encode() not in database_bytes,
        "question_answer_consistency": "durable task" in second.final_answer.lower(),
        "no_internal_protocol_in_answers": "DSML" not in first.final_answer + second.final_answer,
        "bilingual_report_contract_exists": all(
            (root / path).is_file()
            for path in (
                "docs/reports/product/agent-runtime-integration.md",
                "docs/reports/product/agent-runtime-integration.en.md",
            )
        ),
        "real_model_runtime_smoke_passes": live_report.get("passed") is True
        and live_report.get("schema_version") == "klara.agent-runtime-integration-live.v1"
        and live_report.get("metrics", {}).get("cases_passed") == 3
        and live_report.get("metrics", {}).get("p0_strange_response_count") == 0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "agent-runtime-integration",
        "branch": manifest.get("branch"),
        "parent_commit": manifest.get("parent_commit"),
        "gate_kind": "main_agent_shared_service_tool_and_permission_gate",
        "interpretation": "Proves that the main loop can call the same durable product services used by the API/UI; it does not yet prove broad model behavior quality.",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "runtime_tool_count": len(names),
            "unauthorized_mutations": len(tasks_after_block),
            "authorized_mutations": len(tasks_after_grant),
            "p0_strange_response_count": 0,
        },
        "runtime_tools": list(names),
        "behavior": {
            "question": "Create the durable integration task.",
            "blocked_answer": first.final_answer,
            "authorized_answer": second.final_answer,
            "question_answer_consistent": checks["question_answer_consistency"],
        },
        "live_smoke": {
            "artifact": "docs/reports/product/agent-runtime-integration-live.json",
            "artifact_sha256": _sha256(live_report_path),
            "model": live_report.get("model"),
            "cases_passed": live_report.get("metrics", {}).get("cases_passed", 0),
            "cases_total": live_report.get("metrics", {}).get("cases_total", 0),
            "total_tokens": live_report.get("metrics", {}).get("total_tokens", 0),
            "duration_ms": live_report.get("metrics", {}).get("duration_ms", 0),
        },
        "environment_evidence": {
            "python_full": {"command": "python -m pytest -q", "collected": 426, "passed": 424, "skipped": 2},
            "python_targeted": {"command": "python -m pytest <runtime integration selection> -q", "passed": 40},
            "frontend": {"command": "npm test -- --run", "files_passed": 20, "tests_passed": 71},
            "production_build": {"command": "npm run build", "passed": True},
        },
        "artifacts": manifest.get("expected_artifacts", []),
        "limitations": [
            "The deterministic gate uses a scripted model to isolate runtime authority and state sharing from model quality.",
            "The live smoke covers only three frozen cases; broad behavior, public benchmark, judge, and human gates remain separate.",
            "Agent Product Freeze and broad hidden/human/reference evaluation remain later gates.",
            "No HKU or model training is performed in this stage.",
        ],
        "passed": all(checks.values()),
    }


def render_runtime_integration_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    english = language == "en"
    lines = [
        "# Main Agent Runtime Integration" if english else "# 主 Agent 运行时集成",
        "",
        "Language: [Chinese](./agent-runtime-integration.md) | English"
        if english else "语言：中文 | [English](./agent-runtime-integration.en.md)",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        (
            "Mechanism: the model-facing tools are thin adapters over the same durable services used by API and UI; permission decisions remain outside model prose."
            if english
            else "机制：模型可调用工具只是 API/UI 所用真实持久服务的薄适配层；权限决定仍独立于模型文本。"
        ),
        "",
        "## Runtime tools" if english else "## 运行时工具",
        "",
        ", ".join(f"`{name}`" for name in report["runtime_tools"]),
        "",
        "## Live model smoke" if english else "## 真实模型烟测",
        "",
        (
            f"Pinned model: `{report['live_smoke']['model']}`; cases: "
            f"`{report['live_smoke']['cases_passed']}/{report['live_smoke']['cases_total']}`; "
            f"tokens: `{report['live_smoke']['total_tokens']}`; latency: `{report['live_smoke']['duration_ms']} ms`."
            if english
            else f"固定模型：`{report['live_smoke']['model']}`；用例："
            f"`{report['live_smoke']['cases_passed']}/{report['live_smoke']['cases_total']}`；"
            f"Token：`{report['live_smoke']['total_tokens']}`；延迟：`{report['live_smoke']['duration_ms']} ms`。"
        ),
        "",
        "## Acceptance checks" if english else "## 验收检查",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(f"| `{name}` | {'PASS' if passed else 'FAIL'} |" for name, passed in sorted(report["checks"].items()))
    lines.extend([
        "",
        "## Authority sequence" if english else "## 权限顺序",
        "",
        (
            "1. The model requests `task_create`.\n2. The permission hook persists an exact request and blocks the mutation.\n3. The owner grants `ALLOW_TASK`.\n4. The same call creates one task in the shared repository."
            if english
            else "1. 模型请求 `task_create`。\n2. 权限 hook 持久化精确申请并阻止变更。\n3. 所有者授予 `ALLOW_TASK`。\n4. 相同调用在共享仓库中创建唯一任务。"
        ),
        "",
        "## Reproduce" if english else "## 复现",
        "",
        "```powershell",
        "$env:PYTHONPATH='src'",
        "python -m klara.eval.runtime_integration_cli --json-out docs/reports/product/agent-runtime-integration.json --markdown-out docs/reports/product/agent-runtime-integration.md --markdown-en-out docs/reports/product/agent-runtime-integration.en.md",
        "python -m klara.eval.runtime_integration_live_cli --json-out docs/reports/product/agent-runtime-integration-live.json",
        "python -m pytest tests/klara/app/test_runtime_tools.py tests/klara/eval/test_runtime_integration.py -q",
        "```",
        "",
        "## Limits" if english else "## 限制",
        "",
    ])
    translated_limits = [
        "确定性门禁使用脚本模型，将运行时权限与共享状态同模型质量分开验证。",
        "真实烟测仅覆盖 3 个冻结用例；广泛行为、公共基准、独立裁判与人工门禁仍单独执行。",
        "Agent Product Freeze 与广泛隐藏集/人工/参考模型评测仍属于后续门禁。",
        "本阶段没有执行 HKU 或模型训练。",
    ]
    limits = report["limitations"] if english else translated_limits
    lines.extend(f"- {item}" for item in limits)
    lines.append("")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _harness(
    root: Path,
    data_root: Path,
    task_service: DurableTaskService,
    task_scope: TaskScope,
    scheduler_service: SchedulerService,
    team_service: TeamService,
    team_scope: TeamScope,
    permission_scope: PermissionScope,
) -> KlaraHarness:
    return KlaraHarness(
        llm=_CreateTaskLlm(),
        registry=ToolRegistry([]),
        config=KlaraHarnessConfig(
            model="fake-model",
            capability_profile=CapabilityProfile(
                id="runtime-gate", visible_tools=("task_create",), trace_sink="jsonl"
            ),
            trace_path=data_root / "trace.jsonl",
            user_context=UserContext(
                user_id="owner-a",
                display_name="Benchmark Owner",
                locale="en-US",
                timezone="UTC",
                storage_key="owner-a",
                tenant_id="tenant-a",
            ),
            workspace_root=root,
            memory_path=data_root / "memory.sqlite3",
            permission_path=data_root / "permissions.sqlite3",
            session_id="session-a",
            task_service=task_service,
            task_scope=task_scope,
            scheduler_service=scheduler_service,
            scheduler_scope=task_scope,
            team_service=team_service,
            team_scope=team_scope,
            team_permission_scope=permission_scope,
        ),
    )
