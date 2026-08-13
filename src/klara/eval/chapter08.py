"""Machine-check Chapter 8 provider recovery and fallback contracts."""

from __future__ import annotations

from datetime import UTC, datetime
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import urllib.error
import urllib.request
from unittest.mock import patch

from apps.api.services.run_event_projector import RunEventProjector
from klara.app.cli import build_harness
from klara.app.user_context import UserContext
from klara.context.controller import ContextController
from klara.context.policy import ContextPolicy
from klara.core.events import KlaraEvent
from klara.core.hooks import HookManager
from klara.core.loop import KlaraLoop
from klara.core.messages import KlaraMessage, ModelCallError, ModelResponse
from klara.core.policies import LoopPolicy
from klara.core.tools import ToolCall
from klara.infra.config.models import ModelProfile, ModelsConfig, ProviderConfig
from klara.infra.llm.openai_compatible import (
    LlmProviderError,
    OpenAICompatibleLlmClient,
    _urlopen_with_retries,
)
from klara.infra.llm.routed_client import RoutedLlmClient
from klara.tools.executor import ToolExecutor


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter08-provider-recovery.v1"


class _Response:
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return b'{"choices":[{"message":{"content":"ok"}}]}'


class _Recorder:
    def __init__(self) -> None:
        self.events: list[KlaraEvent] = []

    def on_event(self, event: KlaraEvent) -> None:
        self.events.append(event)


class _RecoveryLlm:
    def __init__(self) -> None:
        self.calls: list[tuple[KlaraMessage, ...]] = []
        self.prompts: list[str] = []

    def complete(self, **kwargs: object) -> ModelResponse:
        messages = kwargs["messages"]
        self.calls.append(messages)  # type: ignore[arg-type]
        self.prompts.append(str(kwargs["system_prompt"]))
        if len(self.calls) == 1:
            raise ModelCallError(
                "private-provider-body-should-never-be-public",
                code="context_length_exceeded",
                status_code=400,
            )
        return ModelResponse(content="Recovered answer.")


class _ToolFailureLlm:
    def __init__(self) -> None:
        self.calls = 0
        self.observation = ""

    def complete(self, **kwargs: object) -> ModelResponse:
        self.calls += 1
        messages = kwargs["messages"]
        if self.calls == 1:
            return ModelResponse(
                content="",
                tool_calls=(ToolCall(id="missing-1", name="missing_tool", arguments={}),),
            )
        self.observation = messages[-1].content  # type: ignore[index]
        return ModelResponse(content="The tool was unavailable, so I stopped.")


def evaluate_chapter08(root: Path) -> dict[str, Any]:
    """Run deterministic fault injection through provider, router, loop, and UI."""

    private_marker = "private-provider-body-marker"
    attempts = 0
    slept: list[float] = []

    def fake_urlopen(*args: object, **kwargs: object) -> _Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.HTTPError(
                "https://provider.invalid",
                503,
                "unavailable",
                {},
                io.BytesIO(private_marker.encode("utf-8")),
            )
        return _Response()

    request = urllib.request.Request("https://provider.invalid")
    with patch.object(urllib.request, "urlopen", fake_urlopen), patch(
        "klara.infra.llm.openai_compatible.time.sleep", slept.append
    ):
        _, retry_events = _urlopen_with_retries(
            request,
            provider_id="fixture",
            model="fixture/model",
            timeout_seconds=7,
            attempts=2,
            retry_base_delay_seconds=0.01,
            retry_max_delay_seconds=0.02,
        )

    route_calls: list[str] = []

    def fake_complete(
        self: OpenAICompatibleLlmClient,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[object, ...],
        model: str,
        thinking_enabled: bool | None = None,
    ) -> ModelResponse:
        route_calls.append(model)
        if len(route_calls) == 1:
            raise LlmProviderError(
                "primary unavailable",
                code="provider_unavailable",
                retryable=True,
                status_code=503,
            )
        return ModelResponse(content="fallback ok")

    router = RoutedLlmClient(
        models=ModelsConfig(
            providers={
                "primary": ProviderConfig(api="openai-completions", allow_unlisted_models=True),
                "fallback": ProviderConfig(api="openai-completions", allow_unlisted_models=True),
            },
            profiles={
                "agent": ModelProfile(
                    primary="primary/model-a",
                    fallbacks=("fallback/model-b",),
                )
            },
        )
    )
    with patch.object(OpenAICompatibleLlmClient, "complete", fake_complete):
        routed = router.complete(
            system_prompt="system",
            messages=(KlaraMessage(role="user", content="hello"),),
            tools=(),
            model="primary/model-a",
        )

    with TemporaryDirectory(prefix="klara-ch08-") as temporary:
        temp = Path(temporary)
        recovery_llm = _RecoveryLlm()
        recorder = _Recorder()
        controller = ContextController(
            policy=ContextPolicy(
                max_input_tokens=2_000,
                reserved_system_tokens=300,
                reserved_output_tokens=300,
                recent_messages=4,
                minimum_recent_messages=2,
                summary_max_chars=256,
                tool_result_max_chars=128,
            ),
            user_context=UserContext.local_default(),
            capabilities=(),
            workspace_root=temp,
        )
        prior = tuple(
            KlaraMessage(
                role="user" if index % 2 == 0 else "assistant",
                content=f"history-{index} " + "x" * 500,
            )
            for index in range(8)
        )
        KlaraLoop(
            llm=recovery_llm,
            tool_executor=ToolExecutor(),
            hooks=HookManager([recorder]),
            controllers=(controller,),
            policy=LoopPolicy(max_prompt_recovery_attempts=1),
            model="fixture/model",
            system_prompt="system",
        ).run("current request", prior_messages=prior, run_id="ch08-recovery")

    recovery_types = [str(event.type) for event in recorder.events]
    recovery_trace = json.dumps(
        [event.to_public_dict() for event in recorder.events], ensure_ascii=False
    )
    tool_llm = _ToolFailureLlm()
    tool_result = KlaraLoop(
        llm=tool_llm,
        tool_executor=ToolExecutor(),
        model="fixture/model",
    ).run("use missing tool", run_id="ch08-tool-failure")
    harness = build_harness(
        config_dir=root / "config",
        model=None,
        thinking_enabled=None,
        trace_path=root / "data/traces/ch08-eval.jsonl",
    )
    fallback_event = next(
        event
        for event in routed.runtime_events
        if event.type == "model_route.fallback_started"
    )
    projected = RunEventProjector(selected_model="primary/model-a").project(
        KlaraEvent(
            type=fallback_event.type,
            run_id="ch08-route",
            payload=fallback_event.payload,
        )
    )
    frontend = (root / "apps/web/src/components/ChatWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    retry_types = [event.type for event in retry_events]
    route_types = [event.type for event in routed.runtime_events]
    checks = {
        "stage_manifest_exists": (root / "config/stages/ch08-provider-recovery.manifest.json").exists(),
        "provider_policy_is_frozen": harness.run_profile.provider_recovery_policy
        == harness.config.provider_recovery_policy,
        "transient_failure_retries": attempts == 2 and slept == [0.01],
        "retry_trace_is_ordered": retry_types
        == [
            "provider.attempt_started",
            "provider.attempt_failed",
            "provider.retry_scheduled",
            "provider.attempt_started",
            "provider.attempt_completed",
        ],
        "retry_taxonomy_is_public": retry_events[1].payload.get("error_code")
        == "provider_unavailable",
        "provider_body_is_not_public": private_marker not in repr(retry_events),
        "fallback_uses_second_candidate": route_calls
        == ["primary/model-a", "fallback/model-b"],
        "actual_model_is_recorded": routed.model_used == "fallback/model-b",
        "fallback_route_is_ordered": route_types.index("model_route.candidate_failed")
        < route_types.index("model_route.fallback_started")
        < route_types.index("model_route.candidate_completed"),
        "fallback_is_projected_to_api": bool(projected)
        and projected[0].event_type == "model_route.fallback_started",
        "prompt_recovery_retries_once": len(recovery_llm.calls) == 2,
        "prompt_recovery_compacts": len(recovery_llm.calls[1]) < len(recovery_llm.calls[0]),
        "prompt_recovery_refreshes_system_context": 'summary_status="available"'
        in recovery_llm.prompts[1],
        "prompt_recovery_trace_is_ordered": recovery_types.index("model_call.failed")
        < recovery_types.index("prompt_recovery.started")
        < recovery_types.index("pre_compact.started")
        < recovery_types.index("prompt_recovery.completed"),
        "typed_failure_text_is_not_public": "private-provider-body-should-never-be-public"
        not in recovery_trace,
        "tool_failure_becomes_observation": tool_llm.observation
        == "Unknown tool: missing_tool"
        and tool_result.final_answer.startswith("The tool was unavailable"),
        "frontend_shows_recovery_status": 'aria-label="Provider recovery"' in frontend
        and "Fallback active" in frontend,
        "bilingual_tutorial_exists": all(
            (root / path).exists()
            for path in (
                "docs/chapters/ch08-error-recovery-and-fallback.md",
                "docs/chapters/ch08-error-recovery-and-fallback.en.md",
            )
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch08-provider-recovery",
        "gate_kind": "deterministic_fault_injection_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "provider_attempts": attempts,
            "fallback_candidate_count": len(route_calls),
            "prompt_recovery_attempts": len(recovery_llm.calls) - 1,
            "messages_before_recovery": len(recovery_llm.calls[0]),
            "messages_after_recovery": len(recovery_llm.calls[1]),
        },
        "public_fallback_evidence": fallback_event.payload,
        "interpretation": (
            "Passing proves deterministic transient retry, bounded backoff, typed public "
            "failure events, explicit fallback routing, one context-length compaction retry, "
            "tool-failure observations, and a safe recovery UI. It uses fault injection and "
            "does not claim live-provider uptime, production incident response, or a learned policy."
        ),
        "passed": all(checks.values()),
    }


def render_chapter08_markdown(
    report: dict[str, Any], *, language: str = "zh"
) -> str:
    """Render mirrored Chinese and English evidence reports."""

    english = language == "en"
    title = "Chapter 8 Provider Recovery Gate" if english else "Chapter 8 供应商恢复门禁"
    toggle = (
        "Language: [Chinese](./ch08-provider-recovery.md) | English"
        if english
        else "语言：中文 | [English](./ch08-provider-recovery.en.md)"
    )
    lines = [
        f"# {title}",
        "",
        toggle,
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
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
            f"## {'Public Fallback Evidence' if english else '公开 fallback 证据'}",
            "",
            "```json",
            json.dumps(report["public_fallback_evidence"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            f"## {'Interpretation Boundary' if english else '解释边界'}",
            "",
            report["interpretation"]
            if english
            else (
                "通过表示确定性的故障注入已经证明瞬态重试、有上限的退避、类型化公开失败事件、"
                "显式 fallback 路由、一次上下文超限压缩重试、工具失败观察和安全的恢复状态 UI。"
                "它不代表真实供应商可用率、生产事故响应或学习式恢复策略已经完成。"
            ),
            "",
        ]
    )
    return "\n".join(lines)
