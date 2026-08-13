"""Machine-check the Chapter 5 Todo Planning product contract."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.app.cli import build_harness
from klara.core.messages import ModelResponse
from klara.core.tools import ToolCall
from klara.infra.config.loader import load_models_config
from klara.planning.todo import TodoItem, TodoPlan, apply_todo_update


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter05-todo-planning.v1"


class _PlanningProbeLlm:
    """Deterministic two-turn model fixture for the real product path."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **_: object) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        id="activity-probe",
                        name="update_activity",
                        arguments={"text": "I will make the plan visible."},
                    ),
                    ToolCall(
                        id="todo-probe",
                        name="todo_write",
                        arguments={
                            "operation": "replace",
                            "items": [
                                {"id": "inspect", "title": "Inspect", "status": "completed"},
                                {"id": "build", "title": "Build", "status": "in_progress"},
                                {"id": "verify", "title": "Verify", "status": "pending"},
                            ],
                        },
                    ),
                ),
            )
        return ModelResponse(content="Planning probe complete.")


def evaluate_chapter05(root: Path) -> dict[str, Any]:
    """Run deterministic state, persistence, product-path, and UI checks."""

    config_dir = root / "config"
    models = load_models_config(config_dir)
    harness = build_harness(
        config_dir=config_dir,
        model=models.profile("agent").primary,
        thinking_enabled=None,
        trace_path=root / "data/traces/ch05-eval.jsonl",
    )
    merged = apply_todo_update(
        session_id="probe-session",
        existing=TodoPlan(
            session_id="probe-session",
            version=2,
            items=[
                TodoItem(id="inspect", title="Inspect", status="completed"),
                TodoItem(id="build", title="Build", status="in_progress"),
            ],
        ),
        operation="merge",
        items=[
            TodoItem(id="build", title="Build", status="completed"),
            TodoItem(id="verify", title="Verify", status="in_progress"),
        ],
    )
    one_active_rejected = False
    try:
        TodoPlan(
            session_id="probe-session",
            version=1,
            items=[
                TodoItem(id="one", title="One", status="in_progress"),
                TodoItem(id="two", title="Two", status="in_progress"),
            ],
        )
    except ValueError:
        one_active_rejected = True

    with TemporaryDirectory(prefix="klara-ch05-") as temporary:
        temp = Path(temporary)
        store = JsonlAppStore(temp / "app")
        session = store.create_session()
        trace_path = temp / "traces" / "runs.jsonl"
        service = RunService(
            store=store,
            bus=SSEBus(),
            llm_client=_PlanningProbeLlm(),
            trace_path=str(trace_path),
            default_model="test-model",
            answer_chunk_delay_ms=0,
        )
        created = service.create_run(session.session_id, "Plan this task")
        service._threads[created.run_id].join(timeout=5)
        plan = store.get_todo_plan(session.session_id)
        restored = JsonlAppStore(temp / "app").get_todo_plan(session.session_id)
        events = store.list_events(created.run_id)
        trace_events = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        store.delete_session(session.session_id, trace_path)
        purged = store.get_todo_plan(session.session_id) is None

    frontend_source = (root / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    panel_source = (root / "apps/web/src/components/ChatWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    runtime_prompt = (root / "src/klara/context/runtime.py").read_text(encoding="utf-8")
    checks = {
        "stage_manifest_exists": (root / "config/stages/ch05-todo-planning.manifest.json").exists(),
        "todo_write_model_visible": "todo_write" in harness.run_profile.visible_tools,
        "prompt_scopes_planning": "Answer simple or one-step requests directly" in runtime_prompt,
        "schema_is_versioned": bool(plan and plan.schema_version == "klara.todo-plan.v1"),
        "one_active_item_enforced": one_active_rejected,
        "merge_is_ordered_upsert": [item.id for item in merged.items] == ["inspect", "build", "verify"],
        "merge_advances_version": merged.version == 3,
        "product_path_persisted_plan": bool(plan and plan.version == 1),
        "restart_restores_plan": restored == plan,
        "session_delete_purges_plan": purged,
        "sse_projection_exists": any(event.event_type == "todo_plan_updated" for event in events),
        "trace_contains_plan_observation": any(
            event.get("type") == "tool.completed"
            and event.get("payload", {}).get("tool_result", {}).get("name") == "todo_write"
            for event in trace_events
        ),
        "frontend_consumes_live_and_restored_plan": "todo_plan_updated" in frontend_source and "detail.todo_plan" in frontend_source,
        "frontend_renders_accessible_plan": 'aria-label="Current plan"' in panel_source and "todo-plan-progress" in panel_source,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch05-todo-planning",
        "gate_kind": "deterministic_product_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "todo_items_in_product_probe": len(plan.items) if plan else 0,
            "plan_version_after_probe": plan.version if plan else 0,
            "sse_plan_events": sum(event.event_type == "todo_plan_updated" for event in events),
            "trace_plan_events": sum(
                event.get("type") == "tool.completed"
                and event.get("payload", {}).get("tool_result", {}).get("name") == "todo_write"
                for event in trace_events
            ),
        },
        "probe_plan": plan.model_dump(mode="json") if plan else None,
        "interpretation": "Passing proves the local current-session Todo Planning state machine, persistence, product wiring, trace/SSE projection, and frontend contract. It does not claim general planning quality or ChatGPT equivalence.",
        "passed": all(checks.values()),
    }


def render_chapter05_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    """Render structurally identical Chinese and English gate reports."""

    english = language == "en"
    title = "Chapter 5 Todo Planning Gate" if english else "Chapter 5 Todo Planning 门禁"
    toggle = (
        "Language: [Chinese](./ch05-todo-planning.md) | English"
        if english
        else "语言：中文 | [English](./ch05-todo-planning.en.md)"
    )
    status = "PASS" if report["passed"] else "FAIL"
    lines = [
        f"# {title}",
        "",
        toggle,
        "",
        f"Status: **{status}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Gate kind' if english else '门禁类型'}: `{report['gate_kind']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        "",
        f"## {'Acceptance Checks' if english else '验收检查'}",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {key} | {'PASS' if value else 'FAIL'} |"
        for key, value in sorted(report["checks"].items())
    )
    lines.extend(
        [
            "",
            f"## {'Product Probe' if english else '产品探针'}",
            "",
            "```json",
            json.dumps(report["probe_plan"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            f"## {'Interpretation Boundary' if english else '解释边界'}",
            "",
            report["interpretation"]
            if english
            else "通过证明本地当前会话 Todo Planning 的状态机、持久化、产品入口、trace/SSE 投影与前端契约成立；它不代表通用规划质量或 ChatGPT 等价性。",
            "",
        ]
    )
    return "\n".join(lines)
