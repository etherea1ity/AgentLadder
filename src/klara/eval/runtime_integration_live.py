"""Run a bounded real-model smoke test for Agent runtime service adapters."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from klara.app.harness import KlaraHarness, KlaraHarnessConfig
from klara.app.output_contract import contains_internal_protocol
from klara.app.user_context import UserContext
from klara.infra.config.loader import load_models_config
from klara.infra.config.runtime import CapabilityProfile
from klara.infra.llm.openai_compatible import OpenAICompatibleSettings
from klara.infra.llm.routed_client import RoutedLlmClient
from klara.permissions import PermissionEffect, PermissionScope, PermissionService, SQLitePermissionRepository
from klara.tasks import DurableTaskService, SQLiteTaskRepository, TaskScope
from klara.tools.registry import ToolRegistry


SCHEMA_VERSION = "klara.agent-runtime-integration-live.v1"
SCORER_VERSION = "klara.agent-runtime-integration-live.v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
LIST_PROMPT = "请使用任务工具列出我当前的持久任务，并简洁说明它的状态。"
CREATE_PROMPT = (
    "Create one durable task with the exact title 'Live approval proof' and "
    "the exact description 'Synthetic permission smoke'. Use the durable task tool."
)


def evaluate_runtime_integration_live(
    root: Path,
    *,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Exercise read, blocked mutation, and approved mutation through a real LLM."""

    started = perf_counter()
    with TemporaryDirectory(prefix="klara-runtime-live-") as temporary:
        data_root = Path(temporary)
        trace_path = data_root / "live-trace.jsonl"
        task_service = DurableTaskService(SQLiteTaskRepository(data_root / "tasks.sqlite3"))
        task_scope = TaskScope("tenant-live", "owner-live", "klara")
        task_service.create(
            scope=task_scope,
            title="Verify runtime integration",
            description="Synthetic live-smoke fixture",
            task_id="task_live_fixture",
        )
        permission_path = data_root / "permissions.sqlite3"
        llm = RoutedLlmClient(
            models=load_models_config(root / "config"),
            dotenv_path=str(root / ".env"),
            settings=OpenAICompatibleSettings(
                temperature=0.0,
                timeout_seconds=60,
                retry_attempts=2,
                retry_base_delay_seconds=0.25,
                retry_max_delay_seconds=1.0,
            ),
        )

        list_result = _harness(
            root=root,
            data_root=data_root,
            trace_path=trace_path,
            permission_path=permission_path,
            task_service=task_service,
            task_scope=task_scope,
            llm=llm,
            model=model,
            visible_tools=("task_list",),
        ).run(
            LIST_PROMPT,
            run_id="runtime-live-list",
        )

        create_prompt = CREATE_PROMPT
        blocked_harness = _harness(
            root=root,
            data_root=data_root,
            trace_path=trace_path,
            permission_path=permission_path,
            task_service=task_service,
            task_scope=task_scope,
            llm=llm,
            model=model,
            visible_tools=("task_create",),
        )
        blocked_result = blocked_harness.run(
            create_prompt,
            run_id="runtime-live-create-blocked",
        )
        tasks_after_block = task_service.list(scope=task_scope)
        state = blocked_harness.permission_service.list_state(
            scope=blocked_harness.permission_scope
        )
        pending = [item for item in state["requests"] if item["status"] == "pending"]
        if len(pending) == 1:
            blocked_harness.permission_service.decide_request(
                scope=blocked_harness.permission_scope,
                request_id=str(pending[0]["request_id"]),
                effect=PermissionEffect.ALLOW_TASK,
                expires_seconds=600,
            )

        approved_result = _harness(
            root=root,
            data_root=data_root,
            trace_path=trace_path,
            permission_path=permission_path,
            task_service=task_service,
            task_scope=task_scope,
            llm=llm,
            model=model,
            visible_tools=("task_create",),
        ).run(
            create_prompt,
            run_id="runtime-live-create-approved",
        )
        tasks_after_allow = task_service.list(scope=task_scope)
        events = _read_events(trace_path)

    list_tools = _tool_names(list_result)
    blocked_tools = _tool_names(blocked_result)
    approved_tools = _tool_names(approved_result)
    new_tasks = [item for item in tasks_after_allow if item.task_id != "task_live_fixture"]
    unauthorized_mutations = max(0, len(tasks_after_block) - 1)
    checks = {
        "list_case_selected_task_list": list_tools == ["task_list"],
        "list_answer_matches_observed_task": _contains_any(
            list_result.final_answer,
            "Verify runtime integration",
            "ready",
            "就绪",
        ),
        "list_answer_obeys_concise_request": len(list_result.final_answer) <= 320
        and not _contains_any(
            list_result.final_answer,
            "Synthetic live-smoke fixture",
            "lease",
            "租约",
            "worker",
            "创建时间",
            "attempt_count",
        )
        and "?" not in list_result.final_answer
        and "？" not in list_result.final_answer
        and not _contains_any(
            list_result.final_answer,
            "需要的话",
            "我可以帮",
            "需要我",
            "let me know",
            "I can help",
            "would you like",
        ),
        "mutation_case_selected_task_create": blocked_tools == ["task_create"],
        "mutation_blocked_before_approval": unauthorized_mutations == 0,
        "exact_permission_request_persisted": len(pending) == 1
        and pending[0]["action"]["tool_name"] == "task_create"
        and pending[0]["scope"]["task_id"] == "runtime-live-task",
        "blocked_answer_explains_approval": _contains_any(
            blocked_result.final_answer,
            "approval",
            "permission",
            "批准",
            "授权",
        ),
        "approved_case_repeated_same_tool": approved_tools == ["task_create"],
        "approved_action_created_exactly_one_task": len(new_tasks) == 1
        and new_tasks[0].title == "Live approval proof"
        and new_tasks[0].description == "Synthetic permission smoke",
        "approved_answer_matches_side_effect": len(new_tasks) == 1
        and _contains_any(approved_result.final_answer, "created", "ready", "创建", "已"),
        "approved_answer_omits_internal_scope": not _contains_any(
            approved_result.final_answer,
            "tenant-live",
            "owner-live",
            "Scope:",
        ),
        "public_answers_have_no_internal_protocol": not any(
            contains_internal_protocol(answer)
            for answer in (
                list_result.final_answer,
                blocked_result.final_answer,
                approved_result.final_answer,
            )
        ),
        "trace_omits_private_tool_arguments": "Synthetic permission smoke"
        not in "\n".join(json.dumps(item, ensure_ascii=False) for item in events),
        "requested_model_completed": all(
            _completed_model(events, run_id) == model
            for run_id in (
                "runtime-live-list",
                "runtime-live-create-blocked",
                "runtime-live-create-approved",
            )
        ),
    }
    cases = [
        _case("task-list-zh", list_result, list_tools, events),
        _case("task-create-blocked", blocked_result, blocked_tools, events),
        _case("task-create-approved", approved_result, approved_tools, events),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "agent-runtime-integration-live",
        "model": model,
        "model_config_sha256": _sha256(root / "config/models.toml"),
        "runtime_config_sha256": _sha256(root / "config/runtime.toml"),
        "persona_sha256": _sha256(root / "src/klara/prompts/persona.md"),
        "prompt_sha256": hashlib.sha256(
            json.dumps(
                [LIST_PROMPT, CREATE_PROMPT],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "source_bundle_sha256": _source_bundle_sha256(
            root,
            (
                "src/klara/app/harness.py",
                "src/klara/app/runtime_tools.py",
                "src/klara/core/loop.py",
                "src/klara/permissions/resolver.py",
                "src/klara/prompts/persona.md",
            ),
        ),
        "provider_hidden_reasoning_collected": False,
        "synthetic_fixture_only": True,
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "cases_passed": sum(case["passed"] for case in cases),
            "cases_total": len(cases),
            "unauthorized_mutations": unauthorized_mutations,
            "authorized_mutations": len(new_tasks),
            "p0_strange_response_count": 0
            if checks["public_answers_have_no_internal_protocol"]
            and checks["mutation_blocked_before_approval"]
            and checks["approved_answer_matches_side_effect"]
            else 1,
            "duration_ms": max(0, int((perf_counter() - started) * 1000)),
            "total_tokens": sum(case["metrics"]["total_tokens"] for case in cases),
        },
        "cases": cases,
        "limitations": [
            "This is a three-case live smoke test, not a broad behavior benchmark or a parity claim.",
            "The fixture is synthetic and uses one configured DeepSeek model at temperature 0.",
            "Only public answers, tool names, status, latency, and usage are retained; provider-hidden reasoning is not collected.",
            "The configured Qwen credential was not used in this pinned smoke and is evaluated separately as provider readiness.",
        ],
        "passed": all(checks.values()),
    }


def _harness(
    *,
    root: Path,
    data_root: Path,
    trace_path: Path,
    permission_path: Path,
    task_service: DurableTaskService,
    task_scope: TaskScope,
    llm: RoutedLlmClient,
    model: str,
    visible_tools: tuple[str, ...],
) -> KlaraHarness:
    return KlaraHarness(
        llm=llm,
        registry=ToolRegistry([]),
        models=llm.models,
        controllers=(),
        config=KlaraHarnessConfig(
            model=model,
            capability_profile=CapabilityProfile(
                id="runtime-live",
                required_model_capabilities=("tools",),
                visible_tools=visible_tools,
                trace_sink="jsonl",
            ),
            trace_path=trace_path,
            user_context=UserContext(
                user_id="owner-live",
                display_name="Live Benchmark Owner",
                locale="zh-CN",
                timezone="Asia/Shanghai",
                storage_key="owner-live",
                tenant_id="tenant-live",
            ),
            workspace_root=root,
            memory_path=data_root / "memory.sqlite3",
            permission_path=permission_path,
            session_id="runtime-live-task",
            task_service=task_service,
            task_scope=task_scope,
        ),
    )


def _tool_names(result: Any) -> list[str]:
    return [
        call.name
        for message in result.messages
        if message.role == "assistant"
        for call in message.tool_calls
    ]


def _read_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _completed_model(events: list[dict[str, Any]], run_id: str) -> str | None:
    completed = [
        item["payload"].get("model_used")
        for item in events
        if item.get("run_id") == run_id
        and item.get("type") == "model_route.candidate_completed"
    ]
    return str(completed[-1]) if completed else None


def _case(
    case_id: str,
    result: Any,
    tools: list[str],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = [
        item
        for item in events
        if item.get("run_id") == result.run_id and item.get("type") == "run.completed"
    ]
    metrics = completed[-1]["payload"].get("metrics", {}) if completed else {}
    return {
        "case_id": case_id,
        "run_id": result.run_id,
        "stop_reason": result.stop_reason.value,
        "tool_names": tools,
        "public_answer": result.final_answer,
        "metrics": {
            "duration_ms": int(metrics.get("duration_ms") or 0),
            "total_tokens": int(metrics.get("total_tokens") or 0),
        },
        "passed": result.stop_reason.value == "final" and bool(result.final_answer.strip()),
    }


def _contains_any(value: str, *terms: str) -> bool:
    lowered = value.casefold()
    return any(term.casefold() in lowered for term in terms)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_bundle_sha256(root: Path, relative_paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
