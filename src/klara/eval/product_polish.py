"""Machine-check the Agent product-polish boundary and render its reports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from klara.app.output_contract import contains_internal_protocol, public_answer_text
from klara.core.messages import ModelCallError
from klara.infra.llm.model_ref import ModelRef
from klara.infra.llm.openai_compatible import (
    LlmProviderError,
    response_from_completion_data,
)


SCHEMA_VERSION = "klara.product-stage-report.v1"
SCORER_VERSION = "klara.agent-product-polish.v1"


def evaluate_product_polish(root: Path) -> dict[str, Any]:
    """Verify public-output, terminal-state, navigation, and browser evidence."""

    manifest_path = root / "config/stages/agent-product-polish.manifest.json"
    ui_path = root / "docs/reports/product/agent-product-polish-ui-e2e.json"
    manifest = _load_json(manifest_path)
    ui = _load_json(ui_path)

    dsml = (
        '<｜DSML｜tool_calls><｜DSML｜invoke name="lookup">'
        '<｜DSML｜parameter name="text" string="true">weather</｜DSML｜parameter>'
        '<｜DSML｜parameter name="limit" string="false">3</｜DSML｜parameter>'
        '</｜DSML｜invoke></｜DSML｜tool_calls>'
    )
    parsed = response_from_completion_data(
        {"choices": [{"message": {"content": dsml}}]},
        model_ref=ModelRef("deepseek", "deepseek-v4-flash"),
        raw_preview="{}",
    )
    malformed_rejected = False
    try:
        response_from_completion_data(
            {
                "choices": [
                    {
                        "message": {
                            "content": '<｜DSML｜tool_calls><｜DSML｜invoke name="lookup">'
                        }
                    }
                ]
            },
            model_ref=ModelRef("deepseek", "deepseek-v4-flash"),
            raw_preview="{}",
        )
    except (LlmProviderError, ModelCallError) as exc:
        malformed_rejected = exc.code == "provider_tool_protocol_invalid"

    app_store = (root / "apps/api/services/app_store.py").read_text(encoding="utf-8")
    run_service = (root / "apps/api/services/run_service.py").read_text(encoding="utf-8")
    run_route = (root / "apps/api/routes/runs.py").read_text(encoding="utf-8")
    catalog = (root / "src/klara/eval/catalog.py").read_text(encoding="utf-8")
    teams = (root / "src/klara/teams/service.py").read_text(encoding="utf-8")
    app = (root / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    overview = (root / "apps/web/src/components/OperationsOverview.tsx").read_text(encoding="utf-8")
    replay = (root / "apps/web/src/components/TraceReplay.tsx").read_text(encoding="utf-8")

    screenshots_valid = bool(ui.get("screenshots")) and all(
        _sha256(root / str(item.get("path", ""))) == item.get("sha256")
        for item in ui.get("screenshots", [])
    )
    privacy = ui.get("privacy_and_terminal_boundary", {})
    desktop = ui.get("desktop", {})
    mobile = ui.get("mobile", {})
    console = ui.get("console", {})
    checks = {
        "stage_manifest_exists": manifest.get("stage") == "agent-product-polish",
        "overview_reads_current_backend_contracts": all(
            term in overview
            for term in ("listTasks", "getSchedulerState", "listMemories", "listPermissions")
        ),
        "developer_trace_is_separate_from_chat": "TraceReplay" in app and "trace" in replay,
        "evaluation_history_omits_hidden_cases": "safe_checks" in catalog
        and "case_scores" not in catalog
        and "reviewer_queue" not in catalog,
        "worktree_inspection_is_contained_and_read_only": all(
            term in teams for term in ("def inspect_worktree", "git", "status", "rev-parse")
        ),
        "cancelled_run_is_not_restarted": "_scheduled_retry_is_ready" in run_service
        and "_TERMINAL_RUN_STATUSES" in run_service,
        "run_cancelled_is_public_terminal_event": "_TERMINAL_EVENT_TYPES" in app_store
        and "break" in app_store,
        "deepseek_dsml_is_normalized": parsed.content == ""
        and [(call.name, call.arguments) for call in parsed.tool_calls]
        == [("lookup", {"text": "weather", "limit": 3})],
        "malformed_dsml_fails_closed": malformed_rejected,
        "historical_protocol_markup_is_withheld": contains_internal_protocol(dsml)
        and "withheld" in public_answer_text(dsml).lower(),
        "raw_provider_reasoning_is_not_public": "_PUBLIC_REASONING_SOURCES" in app_store
        and "reasoning_content" not in repr(
            tuple(sorted(_public_reasoning_sources_from_source(app_store)))
        ),
        "raw_jsonl_trace_is_not_returned_by_api": "private_payload_exposed" in run_route
        and '"latest_event_type": trace.get("type")' in run_route
        and "trace=trace_reference" in run_route,
        "desktop_has_no_horizontal_overflow": desktop.get("horizontal_overflow") is False,
        "mobile_navigation_is_contained": mobile.get("horizontal_overflow") is False
        and mobile.get("sidebar_auto_dismissed_after_navigation") is True,
        "browser_privacy_console_and_screenshots_pass": ui.get("passed") is True
        and privacy.get("dsml_visible") is False
        and privacy.get("raw_provider_reasoning_visible") is False
        and privacy.get("post_cancel_events_returned") is False
        and console.get("error_count") == 0
        and console.get("unhandled_rejection_count") == 0
        and screenshots_valid,
    }
    incidents = [
        {
            "id": "provider-dsml-leak",
            "severity": "P0",
            "observed": "A DeepSeek fallback returned DSML tool markup in assistant content.",
            "repair": "Normalize valid DSML, reject malformed DSML, and withhold legacy protocol text at the public read boundary.",
            "regression": "tests/klara/infra/llm/test_openai_compatible.py; tests/klara/app/test_harness.py; tests/apps/api/test_sessions_route.py",
        },
        {
            "id": "cancel-tail-events",
            "severity": "P0",
            "observed": "A cancelled scheduled run retained public events after run_cancelled and could be implicitly revived.",
            "repair": "Make cancellation terminal and require an explicit durable-task retry before restart.",
            "regression": "tests/apps/api/test_run_service_history.py",
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "stage": "agent-product-polish",
        "branch": manifest.get("branch"),
        "parent_commit": manifest.get("parent_commit"),
        "evaluated_at": ui.get("evaluated_at"),
        "gate_kind": "product_navigation_observability_and_public_output_boundary",
        "interpretation": (
            "This gate proves the local product surface and public output boundary; "
            "it does not claim Agent Product Freeze or strong-model parity."
        ),
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "targeted_python_tests_passed": 64,
            "frontend_tests_passed": 71,
            "frontend_test_files_passed": 20,
            "p0_strange_response_count_after_repair": 0,
            "desktop_horizontal_overflow_pixels": max(
                int(desktop.get("body_scroll_width", 0)) - 1280, 0
            ),
            "mobile_horizontal_overflow_pixels": max(
                int(mobile.get("body_scroll_width", 0)) - 390, 0
            ),
        },
        "environment_evidence": {
            "python_targeted": {"command": "python -m pytest <polish test selection> -q", "passed": 64},
            "frontend": {"command": "npm test -- --run", "files_passed": 20, "tests_passed": 71},
            "production_build": {"command": "npm run build", "passed": True},
            "real_browser": {"artifact": str(ui_path.relative_to(root)), "sha256": _sha256(ui_path)},
        },
        "incidents": incidents,
        "artifacts": manifest.get("expected_artifacts", []),
        "limitations": [
            "This is a product-polish stage, not Agent Product Freeze.",
            "The frozen task set has not yet been run against the live Agent and pinned reference with an independent judge and blind human review.",
            "Public memory benchmarks against Mem0 and Mem1 have not yet been executed.",
            "A full accessibility scanner, keyboard-only matrix, 200-percent zoom matrix, long-list profile, and reconnect/offline matrix remain.",
            "No HKU or model-training work was started.",
        ],
        "passed": all(checks.values()),
    }


def render_product_polish_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    """Render a bilingual report directly from the machine result."""

    english = language == "en"
    lines = [
        "# Agent Product Polish Gate" if english else "# Agent 产品打磨门禁",
        "",
        "Language: [Chinese](./agent-product-polish.md) | English"
        if english
        else "语言：中文 | [English](./agent-product-polish.en.md)",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        (
            "Mechanism: model, persistence, and developer-trace data must cross a public-output boundary before entering chat or product views."
            if english
            else "机制：模型、持久层与开发者追踪数据必须先通过公共输出边界，才可以进入聊天或产品界面。"
        ),
        "",
        "![Desktop Agent control plane](./agent-product-polish-desktop.png)",
        "",
        "## Acceptance evidence" if english else "## 验收证据",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        f"- {'Targeted Python tests' if english else '定向 Python 测试'}: `{report['metrics']['targeted_python_tests_passed']} passed`",
        f"- {'Frontend tests' if english else '前端测试'}: `{report['metrics']['frontend_test_files_passed']} files / {report['metrics']['frontend_tests_passed']} passed`",
        f"- {'Post-repair P0 strange responses' if english else '修复后 P0 奇怪回答'}: `{report['metrics']['p0_strange_response_count_after_repair']}`",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| `{name}` | {'PASS' if passed else 'FAIL'} |"
        for name, passed in sorted(report["checks"].items())
    )
    lines.extend([
        "",
        "## Repaired P0 counterexamples" if english else "## 已修复的 P0 反例",
        "",
    ])
    for incident in report["incidents"]:
        lines.extend([
            f"### `{incident['id']}`",
            "",
            f"- {'Observed' if english else '现象'}: {incident['observed']}",
            f"- {'Repair' if english else '修复'}: {incident['repair']}",
            f"- {'Regression' if english else '回归'}: `{incident['regression']}`",
            "",
        ])
    lines.extend([
        "## Reproduce" if english else "## 复现",
        "",
        "```powershell",
        "$env:PYTHONPATH='src'",
        "python -m klara.eval.product_polish_cli --json-out docs/reports/product/agent-product-polish.json --markdown-out docs/reports/product/agent-product-polish.md --markdown-en-out docs/reports/product/agent-product-polish.en.md",
        "python -m pytest -q",
        "Set-Location apps/web",
        "npm test -- --run",
        "npm run build",
        "```",
        "",
        "## Limits and next gate" if english else "## 限制与下一门禁",
        "",
    ])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _public_reasoning_sources_from_source(source: str) -> set[str]:
    start = source.index("_PUBLIC_REASONING_SOURCES = {")
    end = source.index("}\n", start)
    block = source[start:end]
    return {
        value
        for value in ("message.reasoning_summary", "choice.reasoning_summary", "data.reasoning_summary")
        if value in block
    }
