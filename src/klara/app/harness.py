"""Application-layer harness that assembles one Klara run."""

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
    """Configuration needed to assemble a Chapter 1 loop run."""

    # Model id is passed through to the injected LLM client.
    model: str = "fake-model"
    # Trace path is optional so tests can choose when to write JSONL.
    trace_path: Path | None = None
    # Max turns bounds the loop before a real policy system exists.
    max_turns: int = 4
    # User context is local-only in Chapter 1, but keeps future partitioning stable.
    user_context: UserContext = field(default_factory=UserContext.local_default)
    # Persona prompt stays in app so core does not own product identity.
    persona_path: Path = Path(__file__).parents[1] / "prompts" / "persona.md"


class KlaraHarness:
    """Assemble persona, user context, tools, trace, policy, and loop.

    The harness owns run setup. It does not implement loop execution, concrete
    tool behavior, memory, RAG, backend streaming, or production auth.
    """

    def __init__(
        self,
        *,
        llm: LlmClient,
        registry: CapabilityRegistry | None = None,
        config: KlaraHarnessConfig | None = None,
    ) -> None:
        """Create a harness around an injected LLM client.

        Args:
            llm: Model client used by the loop.
            registry: Optional capability registry for visible tools.
            config: Optional run-assembly configuration.
        """

        # LLM stays injected so Chapter 1 can run with deterministic fake models.
        self.llm = llm
        # Registry defaults to the single Chapter 1 demonstration tool.
        self.registry = registry or CapabilityRegistry.with_default_chapter1_tools()
        # Config owns local user context, model id, prompt path, and trace path.
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

        # The harness converts visible capabilities into the core executor boundary.
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
        """Build the minimal system prompt from persona and local user context."""

        # Persona text carries Klara's identity without entering core.
        persona = self.config.persona_path.read_text(encoding="utf-8").strip()
        # User context is prompt-visible only through selected public fields.
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
