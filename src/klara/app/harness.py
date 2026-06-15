from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from klara.app.user_context import UserContext
from klara.capabilities.registry import CapabilityRegistry
from klara.core.hooks import HookManager, JsonlTraceHook
from klara.core.loop import KlaraLoop, KlaraRunResult, LlmClient
from klara.core.policies import LoopPolicy
from klara.core.tool_executor import ToolExecutor


@dataclass(frozen=True)
class KlaraHarnessConfig:
    model: str = "fake-model"
    trace_path: Path | None = None
    max_turns: int = 4
    user_context: UserContext = field(default_factory=UserContext.local_default)
    persona_path: Path = Path(__file__).parents[1] / "prompts" / "persona.md"


class KlaraHarness:
    def __init__(
        self,
        *,
        llm: LlmClient,
        registry: CapabilityRegistry | None = None,
        config: KlaraHarnessConfig | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry or CapabilityRegistry.with_default_chapter1_tools()
        self.config = config or KlaraHarnessConfig()

    def run(self, user_input: str, *, run_id: str | None = None) -> KlaraRunResult:
        hooks = HookManager()
        if self.config.trace_path is not None:
            hooks.register(JsonlTraceHook(self.config.trace_path))

        loop = KlaraLoop(
            llm=self.llm,
            tool_executor=ToolExecutor(list(self.registry.visible_tools())),
            hooks=hooks,
            policy=LoopPolicy(max_turns=self.config.max_turns),
            model=self.config.model,
            system_prompt=self._system_prompt(),
        )
        return loop.run(user_input, run_id=run_id)

    def _system_prompt(self) -> str:
        persona = self.config.persona_path.read_text(encoding="utf-8").strip()
        user = self.config.user_context
        return "\n\n".join(
            [
                persona,
                (
                    "Runtime user context:\n"
                    f"- display_name: {user.display_name}\n"
                    f"- locale: {user.locale}\n"
                    f"- timezone: {user.timezone}"
                ),
            ]
        )
