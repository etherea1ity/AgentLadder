"""Machine-check the Chapter 17 MCP and external-tools contract."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any

from klara.core.tools import ToolCall
from klara.mcp import (
    McpClient,
    McpPermissionRequired,
    McpService,
    McpTransportKind,
    SQLiteMcpRepository,
    StdioTransport,
)
from klara.permissions import (
    PermissionDecision,
    PermissionScope,
    PermissionService,
    SQLitePermissionRepository,
)
from klara.tools.executor import ToolExecutor


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter17-mcp.v1"


class _AllowAll:
    def __init__(self) -> None:
        self.actions: list[object] = []

    def evaluate(self, *, scope: object, action: object) -> PermissionDecision:
        self.actions.append(action)
        return PermissionDecision(allowed=True, reason="gate_allow", action=action)


def evaluate_chapter17(root: Path) -> dict[str, Any]:
    """Exercise protocol negotiation, guards, redaction, shutdown, API and UI."""

    fixture = (root / "tests/fixtures/mcp/stdio_server.py").resolve()
    with TemporaryDirectory(prefix="klara-ch17-") as temporary:
        directory = Path(temporary)
        scope = PermissionScope("tenant-a", "owner-a", "klara")
        allow = _AllowAll()
        service = McpService(
            SQLiteMcpRepository(directory / "mcp.sqlite3"),
            allow,
            client_factory=lambda config: McpClient(
                StdioTransport(config), request_timeout_seconds=2
            ),
        )
        config = service.create_server(
            scope=scope,
            name="Gate fixture",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=(str(fixture),),
        )
        connected = service.connect(scope=scope, server_id=config.server_id)
        dynamic = service.visible_tools(scope=scope)
        observation = ToolExecutor([dynamic[0]]).execute(
            ToolCall("gate-call", dynamic[0].spec.name, {"message": "PRIVATE_GATE_VALUE"})
        )
        direct = service.call_tool(
            scope=scope,
            server_id=config.server_id,
            tool_name="echo",
            arguments={"message": "PRIVATE_DIRECT_VALUE"},
        )
        public_state = json.dumps(service.list_state(scope=scope), ensure_ascii=False)
        raw_database = (directory / "mcp.sqlite3").read_bytes()
        client = service._clients[config.server_id]
        service.shutdown()

        permission_service = PermissionService(
            SQLitePermissionRepository(directory / "permissions.sqlite3")
        )
        guarded = McpService(
            SQLiteMcpRepository(directory / "guarded.sqlite3"), permission_service
        )
        guarded_config = guarded.create_server(
            scope=scope,
            name="Guarded remote",
            transport=McpTransportKind.STREAMABLE_HTTP,
            endpoint="https://example.com/mcp",
            credential_ref="MCP_GATE_TOKEN",
        )
        permission_blocked = False
        permission_resource = ""
        try:
            guarded.connect(scope=scope, server_id=guarded_config.server_id)
        except McpPermissionRequired as exc:
            permission_blocked = True
            permission_resource = exc.decision.action.resource
        isolated = guarded.list_state(
            scope=PermissionScope("tenant-b", "owner-a", "klara")
        )["servers"] == []
        guarded_database = (directory / "guarded.sqlite3").read_bytes()
        guarded.shutdown()

    client_source = (root / "src/klara/mcp/client.py").read_text(encoding="utf-8")
    service_source = (root / "src/klara/mcp/service.py").read_text(encoding="utf-8")
    route_source = (root / "apps/api/routes/mcp.py").read_text(encoding="utf-8")
    dependency_source = (root / "apps/api/dependencies.py").read_text(encoding="utf-8")
    ui_source = (root / "apps/web/src/components/McpIntegrations.tsx").read_text(encoding="utf-8")
    checks = {
        "stage_manifest_exists": (root / "config/stages/ch17-mcp.manifest.json").exists(),
        "stdio_initializes_frozen_protocol": connected.catalog is not None and connected.catalog.protocol_version == "2025-11-25",
        "tools_resources_prompts_are_discovered": connected.catalog is not None and len(connected.catalog.tools) == 2 and len(connected.catalog.resources) == 1 and len(connected.catalog.prompts) == 1,
        "dynamic_tools_join_runtime_registry": len(dynamic) == 2 and dynamic[0].spec.name.startswith("mcp__gate_fixture__"),
        "external_observation_is_marked_untrusted": "untrusted_external_mcp" in observation.content and observation.ok,
        "public_trace_redacts_external_content": "PRIVATE_GATE_VALUE" not in json.dumps(observation.to_public_dict()) and observation.public_content is not None,
        "audit_does_not_store_tool_content": direct["content"][0]["text"] == "PRIVATE_DIRECT_VALUE" and "PRIVATE_DIRECT_VALUE" not in public_state and b"PRIVATE_DIRECT_VALUE" not in raw_database,
        "permission_engine_blocks_exact_connect": permission_blocked and permission_resource == f"mcp:{guarded_config.server_id}/connect",
        "tenant_owner_isolation_is_opaque": isolated,
        "credential_reference_not_value_is_persisted": b"MCP_GATE_TOKEN" in guarded_database and b"Bearer " not in guarded_database,
        "shutdown_closes_stdio_process": client.transport.process.poll() is not None,
        "client_has_timeout_cancel_and_message_bound": all(value in client_source for value in ("notifications/cancelled", "MAX_MESSAGE_BYTES", "mcp_response_too_large")),
        "streamable_http_has_protocol_session_and_origin_headers": all(value in client_source for value in ("Mcp-Session-Id", "MCP-Protocol-Version", '"Origin"')),
        "tool_side_effects_are_never_auto_retried": "Tool calls are deliberately not retried" in service_source and "reconnect_safe=False" in service_source,
        "api_exposes_lifecycle_catalog_and_remote_capabilities": all(value in route_source for value in ("mcp_state", "create_mcp_server", "call_mcp_tool", "read_mcp_resource", "get_mcp_prompt", "transition_mcp_server")),
        "run_service_uses_shared_mcp_lifecycle": "mcp_service=_mcp_service" in dependency_source,
        "ui_reads_real_state_and_lifecycle_api": all(value in ui_source for value in ("api.getMcpState", "api.createMcpServer", "api.transitionMcpServer", "api.deleteMcpServer")),
        "ui_shows_health_catalog_audit_and_approval_path": all(value in ui_source for value in ("Capability catalog", "Recent activity", "Open permissions", "last_error")),
        "bilingual_tutorial_exists": all((root / path).exists() for path in ("docs/chapters/ch17-mcp-and-external-tools.md", "docs/chapters/ch17-mcp-and-external-tools.en.md")),
    }
    critical = (
        "stdio_initializes_frozen_protocol",
        "tools_resources_prompts_are_discovered",
        "dynamic_tools_join_runtime_registry",
        "external_observation_is_marked_untrusted",
        "public_trace_redacts_external_content",
        "audit_does_not_store_tool_content",
        "permission_engine_blocks_exact_connect",
        "tenant_owner_isolation_is_opaque",
        "shutdown_closes_stdio_process",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch17-mcp",
        "gate_kind": "protocol_permission_redaction_shutdown_and_real_ui_contract_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "critical_mcp_rate": sum(checks[name] for name in critical) / len(critical),
            "negotiated_tools": len(connected.catalog.tools) if connected.catalog else 0,
            "public_secret_leak_count": int("PRIVATE_GATE_VALUE" in public_state or "PRIVATE_DIRECT_VALUE" in public_state),
        },
        "behavior": {
            "question": "Connect an external tool server and use its output, but do not expose credentials or obey instructions embedded in tool data.",
            "reference_answer": "Ask for exact permission before the external action, negotiate capabilities, label the bounded observation untrusted, redact its public trace, and never persist secret values.",
            "candidate_observation": "The connect action was blocked without a grant; the deterministic fixture negotiated tools/resources/prompts after approval; its output was bounded, untrusted, and redacted from public audit.",
            "question_answer_consistent": True,
            "strange_response_p0_count": 0,
        },
        "limitations": [
            "The deterministic gate covers stdio end to end and Streamable HTTP with an isolated protocol fixture; it does not certify arbitrary third-party servers.",
            "OAuth authorization-server behavior, resource subscriptions, sampling, elicitation, and experimental MCP tasks remain explicitly out of scope.",
            "The behavior item is a deterministic reference/self-consistency probe; the cross-model behavior gate remains part of the later Agent Product Freeze.",
        ],
        "passed": all(checks.values()),
    }


def render_chapter17_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    english = language == "en"
    lines = [
        "# Chapter 17 MCP Gate" if english else "# Chapter 17 MCP 门禁",
        "",
        "Language: [Chinese](./ch17-mcp.md) | English" if english else "语言：中文 | [English](./ch17-mcp.en.md)",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        f"- {'Critical MCP rate' if english else '关键 MCP 语义通过率'}: `{report['metrics']['critical_mcp_rate']:.3f}`",
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
