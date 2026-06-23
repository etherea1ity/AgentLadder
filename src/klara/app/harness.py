"""Application-layer harness that assembles one Klara run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from klara.app.user_context import UserContext
from klara.context.runtime import build_system_prompt
from klara.core.hooks import HookManager, JsonlTraceHook
from klara.core.loop import KlaraLoop, KlaraRunResult, LlmClient
from klara.core.policies import LoopPolicy
from klara.services.web import WebResearchController
from klara.tools.executor import ToolExecutor
from klara.tools.registry import ToolRegistry


DEFAULT_LOOP_POLICY = LoopPolicy()


@dataclass(frozen=True)
class KlaraHarnessConfig:
    """Configuration needed to assemble one loop run."""

    # Model id is passed through to the injected LLM client.
    model: str = "fake-model"
    # Trace path is optional so tests can choose when to write JSONL.
    trace_path: Path | None = None
    # Loop policy knobs keep runtime limits configurable outside core.
    max_turns: int = DEFAULT_LOOP_POLICY.max_turns
    max_tool_calls: int = DEFAULT_LOOP_POLICY.max_tool_calls
    max_repeated_tool_calls: int = DEFAULT_LOOP_POLICY.max_repeated_tool_calls
    # User context is local-only and kept for future partitioning.
    user_context: UserContext = field(default_factory=UserContext.local_default)
    # Persona prompt stays in app so core does not own product identity.
    persona_path: Path = Path(__file__).parents[1] / "prompts" / "persona.md"


class KlaraHarness:
    """Assemble persona, tools, trace, policy, and loop.

    The harness owns run setup. It does not implement loop execution, concrete
    tool behavior, memory, RAG, backend streaming, or production auth.
    """

    def __init__(
        self,
        *,
        llm: LlmClient,
        registry: ToolRegistry | None = None,
        config: KlaraHarnessConfig | None = None,
    ) -> None:
        """Create a harness around an injected LLM client.

        Args:
            llm: Model client used by the loop.
            registry: Optional tool registry for visible tools.
            config: Optional run-assembly configuration.
        """

        # LLM stays injected so tests can run with deterministic fake models.
        self.llm = llm
        # Registry defaults to discovered local tools.
        self.registry = registry or ToolRegistry.with_default_tools()
        # Config owns local model id, prompt path, trace path, and future partition context.
        self.config = config or KlaraHarnessConfig()

    def run(self, user_input: str, *, run_id: str | None = None) -> KlaraRunResult:
        """Assemble and execute one Klara loop run.

        Args:
            user_input: User message that starts the run.
            run_id: Optional stable id for deterministic trace tests.

        Returns:
            Final loop result produced by `KlaraLoop`.
        """

        # Hooks are built per run so trace sinks do not leak across executions.
        hooks = HookManager()
        if self.config.trace_path is not None:
            hooks.register(JsonlTraceHook(self.config.trace_path))

        # The harness converts visible tools into the executor boundary.
        loop = KlaraLoop(
            llm=self.llm,
            tool_executor=ToolExecutor(list(self.registry.visible_tools())),
            hooks=hooks,
            policy=LoopPolicy(
                max_turns=self.config.max_turns,
                max_tool_calls=self.config.max_tool_calls,
                max_repeated_tool_calls=self.config.max_repeated_tool_calls,
            ),
            controllers=(
                WebResearchController(user_timezone=self.config.user_context.timezone),
            ),
            model=self.config.model,
            system_prompt=self._system_prompt(),
        )
        return loop.run(user_input, run_id=run_id)

    def _system_prompt(self) -> str:
        """Build the persona prompt plus date-only runtime context."""

        return build_system_prompt(
            persona=self.config.persona_path.read_text(encoding="utf-8"),
            timezone_name=self.config.user_context.timezone,
        )
