"""Clean-context one-shot execution adapter for the product harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from klara.app.harness import KlaraHarness, KlaraHarnessConfig
from klara.app.user_context import UserContext
from klara.core.loop import LlmClient
from klara.core.policies import LoopPolicy
from klara.infra.config.models import ModelsConfig
from klara.infra.config.runtime import CapabilityProfile, ProviderRecoveryPolicy
from klara.teams.models import OneShotExecution, OneShotRequest
from klara.tools.registry import ToolRegistry


@dataclass
class KlaraOneShotExecutor:
    """Run an explicit task packet without parent transcript or hidden context."""

    llm: LlmClient
    model: str
    models: ModelsConfig | None
    user_context: UserContext
    workspace_root: Path
    data_root: Path
    loop_policy: LoopPolicy
    provider_recovery_policy: ProviderRecoveryPolicy

    def __call__(self, request: OneShotRequest, agent_id: str, child_task_id: str) -> OneShotExecution:
        profile = CapabilityProfile(
            id="one-shot-subagent",
            visible_tools=request.capability_names,
            hooks=(),
            trace_sink="none",
        )
        harness = KlaraHarness(
            llm=self.llm,
            registry=ToolRegistry.with_default_tools(),
            config=KlaraHarnessConfig(
                model=request.model or self.model,
                thinking_enabled=False,
                capability_profile=profile,
                trace_path=None,
                loop_policy=self.loop_policy,
                user_context=self.user_context,
                provider_recovery_policy=self.provider_recovery_policy,
                workspace_root=self.workspace_root,
                memory_path=self.data_root / "memory.sqlite3",
                permission_path=self.data_root / "permissions.sqlite3",
                session_id=child_task_id,
                agent_id=agent_id,
            ),
            models=self.models,
        )
        packet = (
            "<delegated_task>\n"
            f"Title: {request.title}\n"
            f"Instructions: {request.instructions}\n"
            "Return a concise result for the parent agent. Do not assume access to the parent conversation.\n"
            "</delegated_task>"
        )
        result = harness.run(packet, run_id=child_task_id, prior_messages=())
        return OneShotExecution(
            summary=result.final_answer,
            public_metrics={
                "message_count": len(result.messages),
                "stop_reason": result.stop_reason.value,
            },
        )
