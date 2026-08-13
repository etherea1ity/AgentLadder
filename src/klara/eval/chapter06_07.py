"""Machine-check Chapters 6-7 context assembly and compression contracts."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from apps.api.schemas import MessageRecord
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.app.cli import build_harness
from klara.context.budget import compact_transcript
from klara.context.policy import ContextPolicy
from klara.core.messages import KlaraMessage, ModelResponse
from klara.infra.config.loader import load_models_config


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter06-07-context.v1"


class _CaptureContextLlm:
    """Capture the actual first model request on the local product path."""

    def __init__(self) -> None:
        self.system_prompt = ""
        self.messages: tuple[KlaraMessage, ...] = ()

    def complete(self, **kwargs: object) -> ModelResponse:
        self.system_prompt = str(kwargs["system_prompt"])
        self.messages = kwargs["messages"]  # type: ignore[assignment]
        return ModelResponse(content="Context probe complete.")


def evaluate_chapter06_07(root: Path) -> dict[str, Any]:
    """Run the real app path plus deterministic budget edge-case probes."""

    config_dir = root / "config"
    models = load_models_config(config_dir)
    harness = build_harness(
        config_dir=config_dir,
        model=models.profile("agent").primary,
        thinking_enabled=None,
        trace_path=root / "data/traces/ch06-07-eval.jsonl",
    )
    policy = ContextPolicy(
        max_input_tokens=640,
        reserved_system_tokens=128,
        reserved_output_tokens=128,
        recent_messages=3,
        minimum_recent_messages=2,
        summary_max_chars=128,
        tool_result_max_chars=80,
    )
    private_marker = "private-context-marker"
    with TemporaryDirectory(prefix="klara-ch06-07-") as temporary:
        temp = Path(temporary)
        store = JsonlAppStore(temp / "app")
        session = store.create_session()
        for index in range(10):
            store.save_message(
                MessageRecord(
                    session_id=session.session_id,
                    role="user" if index % 2 == 0 else "assistant",
                    content=f"{private_marker}-{index} " + ("x" * 360),
                    status="completed",
                    created_at=f"2026-08-13T00:00:{index:02d}+00:00",
                )
            )
        llm = _CaptureContextLlm()
        trace_path = temp / "traces" / "runs.jsonl"
        service = RunService(
            store=store,
            bus=SSEBus(),
            llm_client=llm,
            trace_path=str(trace_path),
            default_model="test-model",
            answer_chunk_delay_ms=0,
            context_policy=policy,
        )
        created = service.create_run(session.session_id, "keep-current-request")
        service._threads[created.run_id].join(timeout=5)
        events = store.list_events(created.run_id)
        trace_text = trace_path.read_text(encoding="utf-8")
        trace_events = [json.loads(line) for line in trace_text.splitlines() if line]

    old_tool = KlaraMessage(
        role="tool",
        name="web_fetch",
        tool_call_id="fetch-1",
        content="source " + ("z" * 900),
    )
    micro_prepared, _, micro_metrics = compact_transcript(
        [
            KlaraMessage(role="assistant", content="fetching"),
            old_tool,
            KlaraMessage(role="user", content="continue"),
            KlaraMessage(role="assistant", content="working"),
            KlaraMessage(role="user", content="finish"),
        ],
        policy=ContextPolicy(
            max_input_tokens=2_000,
            reserved_system_tokens=100,
            reserved_output_tokens=100,
            recent_messages=3,
            minimum_recent_messages=2,
            summary_max_chars=256,
            tool_result_max_chars=80,
        ),
    )
    compacted_event = next(
        (event for event in events if event.event_type == "context.compacted"),
        None,
    )
    placement_events = [
        event
        for event in events
        if event.event_type.startswith("hook_placement")
        and event.payload.get("placement") == "PreCompact"
    ]
    prompt = llm.system_prompt
    frontend = (root / "apps/web/src/components/ChatWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    run_service = (root / "apps/api/services/run_service.py").read_text(
        encoding="utf-8"
    )
    checks = {
        "stage_manifest_exists": (root / "config/stages/ch06-07-context.manifest.json").exists(),
        "context_policy_frozen_in_run_profile": harness.run_profile.to_public_dict()["context_policy"]
        == harness.config.context_policy.to_public_dict(),
        "named_context_sections_reach_model": all(
            section in prompt
            for section in (
                "<workspace_context>",
                "<user_context>",
                "<capability_context>",
                "<session_context",
            )
        ),
        "private_summary_reaches_model": private_marker in prompt,
        "private_summary_absent_from_public_trace": private_marker not in trace_text,
        "history_compacts_before_first_llm": len(llm.messages) < 11
        and any(event.get("type") == "pre_compact.started" for event in trace_events)
        and next(event["type"] for event in trace_events if event["type"] in {"pre_compact.started", "llm.started"})
        == "pre_compact.started",
        "current_request_is_preserved": any(
            "keep-current-request" in message.content for message in llm.messages
        ),
        "compaction_respects_budget": bool(compacted_event)
        and int(compacted_event.payload["after_estimated_tokens"])
        <= int(compacted_event.payload["budget_tokens"]),
        "public_events_expose_metrics_not_summary": bool(compacted_event)
        and compacted_event.payload.get("summary_content_exposed") is False
        and bool(compacted_event.payload.get("summary_sha256"))
        and "summary_content" not in compacted_event.payload,
        "precompact_hook_is_projected": len(placement_events) == 2,
        "tool_micro_compaction_preserves_join_id": micro_metrics["tool_results_micro_compacted"] == 1
        and any(
            message.tool_call_id == "fetch-1"
            and "older tool observation compacted" in message.content
            for message in micro_prepared
        ),
        "history_is_budgeted_not_fixed_count_truncated": "MAX_HISTORY_MESSAGES" not in run_service
        and "prepare_conversation_history(history)" in run_service,
        "frontend_shows_safe_context_budget_status": 'aria-label="Context budget"' in frontend
        and "messages_summarized" in frontend,
        "chapter06_bilingual_tutorial_exists": all(
            (root / path).exists()
            for path in (
                "docs/chapters/ch06-system-prompt-and-context-assembly.md",
                "docs/chapters/ch06-system-prompt-and-context-assembly.en.md",
            )
        ),
        "chapter07_bilingual_tutorial_exists": all(
            (root / path).exists()
            for path in (
                "docs/chapters/ch07-context-compression.md",
                "docs/chapters/ch07-context-compression.en.md",
            )
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch06-07-context",
        "gate_kind": "deterministic_product_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "history_messages_before_current": 10,
            "model_messages_after_compaction": len(llm.messages),
            "messages_summarized": (
                int(compacted_event.payload["messages_summarized"])
                if compacted_event
                else 0
            ),
            "precompact_projected_events": len(placement_events),
            "tool_results_micro_compacted": int(
                micro_metrics["tool_results_micro_compacted"]
            ),
        },
        "public_compaction_evidence": compacted_event.payload if compacted_event else None,
        "interpretation": (
            "Passing proves deterministic local context assembly, pre-call budget enforcement, "
            "recent-message preservation, tool micro-compaction, private-summary boundaries, "
            "public trace/SSE projection, and the safe UI indicator. It does not claim semantic "
            "LLM summarization, durable memory, RAG retrieval, or learned context selection."
        ),
        "passed": all(checks.values()),
    }


def render_chapter06_07_markdown(
    report: dict[str, Any], *, language: str = "zh"
) -> str:
    """Render structurally identical Chinese and English gate reports."""

    english = language == "en"
    title = "Chapters 6-7 Context Gate" if english else "Chapter 6–7 上下文门禁"
    toggle = (
        "Language: [Chinese](./ch06-07-context.md) | English"
        if english
        else "语言：中文 | [English](./ch06-07-context.en.md)"
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
            f"## {'Public Compaction Evidence' if english else '公开压缩证据'}",
            "",
            "```json",
            json.dumps(
                report["public_compaction_evidence"],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            f"## {'Interpretation Boundary' if english else '解释边界'}",
            "",
            (
                report["interpretation"]
                if english
                else "通过证明了确定性的本地上下文组装、首次调用前预算约束、近期消息保留、工具微压缩、私有摘要边界、公开 trace/SSE 投影和安全的前端状态。它不代表语义 LLM 摘要、长期记忆、RAG 检索或学习式上下文选择已经完成。"
            ),
            "",
        ]
    )
    return "\n".join(lines)
