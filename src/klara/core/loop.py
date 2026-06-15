"""Core loop execution for Klara's minimal runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from klara.core.events import KlaraEvent
from klara.core.hooks import HookManager
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.policies import LoopPolicy, StopReason
from klara.core.tool_executor import ToolExecutor
from klara.core.tools import ToolSpec


class LlmClient(Protocol):
    """Protocol for any model client that can serve the Klara loop."""

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
        model: str,
    ) -> ModelResponse:
        """Produce one assistant response for the current model-visible state.

        Args:
            system_prompt: Runtime prompt assembled by the harness.
            messages: Current transcript visible to the model.
            tools: Tool specs visible in this run.
            model: Model identifier selected by the harness.

        Returns:
            Assistant content plus optional tool calls.
        """

        ...


@dataclass(frozen=True)
class KlaraRunResult:
    """Final public result of one Klara loop execution."""

    # Run id joins the result with JSONL trace events.
    run_id: str
    # Messages preserve the final model-visible transcript for tests and replay.
    messages: tuple[KlaraMessage, ...]
    # Final answer is the user-facing assistant text or last observation at max turns.
    final_answer: str
    # Stop reason makes loop termination explicit and testable.
    stop_reason: StopReason
    # Hook failures are visible without changing successful loop semantics.
    hook_failures: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class KlaraLoop:
    """Execute bounded model turns, tool observations, and lifecycle events.

    The loop owns runtime execution only. It does not choose persona, load
    memory, select capability profiles, query RAG, or talk to backend transports.
    Those concerns attach around the loop through harness, capabilities, hooks,
    context, or trace.
    """

    def __init__(
        self,
        *,
        llm: LlmClient,
        tool_executor: ToolExecutor,
        hooks: HookManager | None = None,
        policy: LoopPolicy | None = None,
        model: str = "fake-model",
        system_prompt: str = "",
    ) -> None:
        """Create a loop with injected model, tools, hooks, and policy.

        Args:
            llm: Model client used for each assistant turn.
            tool_executor: Executor for tools visible in this run.
            hooks: Optional hook manager for lifecycle events.
            policy: Optional stop/bounds policy.
            model: Model identifier passed through to the LLM client.
            system_prompt: Prompt assembled outside core by the harness.
        """

        # Dependencies are injected so core stays independent of providers/services.
        self.llm = llm
        self.tool_executor = tool_executor
        self.hooks = hooks or HookManager()
        self.policy = policy or LoopPolicy()
        self.model = model
        self.system_prompt = system_prompt

    def run(self, user_input: str, *, run_id: str | None = None) -> KlaraRunResult:
        """Run the loop until final answer, max turns, or unexpected failure.

        Args:
            user_input: User message that starts this run.
            run_id: Optional stable id for deterministic traces and tests.

        Returns:
            A run result with final transcript, answer, stop reason, and hook
            failures.
        """

        # Active run id is the trace join key across all lifecycle events.
        active_run_id = run_id or str(uuid4())
        # Messages begin with exactly one user message; later turns append to it.
        messages: list[KlaraMessage] = [KlaraMessage(role="user", content=user_input)]
        self._emit(active_run_id, "run.started", {"model": self.model})

        try:
            # Iterate through bounded turns so a model cannot request tools forever.
            for turn_index in range(1, self.policy.max_turns + 1):
                self._emit(active_run_id, "turn.started", {"turn_index": turn_index})
                self._emit(active_run_id, "llm.started", {"turn_index": turn_index})
                # Ask the injected model using only the prompt, transcript, and specs.
                response = self.llm.complete(
                    system_prompt=self.system_prompt,
                    messages=tuple(messages),
                    tools=self.tool_executor.specs,
                    model=self.model,
                )
                self._emit(
                    active_run_id,
                    "llm.completed",
                    {
                        "turn_index": turn_index,
                        "tool_call_count": len(response.tool_calls),
                        "usage": response.usage or {},
                    },
                )
                # Store the assistant request before tools so replay matches transcript.
                assistant_message = KlaraMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
                messages.append(assistant_message)

                if not response.tool_calls:
                    # No tool calls means the assistant content is the final answer.
                    self._emit(active_run_id, "turn.completed", {"turn_index": turn_index})
                    return self._complete(
                        active_run_id,
                        messages,
                        response.content,
                        StopReason.FINAL,
                    )

                # Execute every requested tool before preparing the next model turn.
                for call in response.tool_calls:
                    self._emit(
                        active_run_id,
                        "tool.started",
                        {"turn_index": turn_index, "tool_call": call.to_public_dict()},
                    )
                    # Tool results become model-visible observations.
                    result = self.tool_executor.execute(call)
                    self._emit(
                        active_run_id,
                        "tool.completed",
                        {
                            "turn_index": turn_index,
                            "tool_result": result.to_public_dict(),
                        },
                    )
                    messages.append(
                        KlaraMessage(
                            role="tool",
                            name=result.name,
                            tool_call_id=result.tool_call_id,
                            content=result.content if result.ok else result.error or "",
                        )
                    )

                # Chapter 1 keeps preparation as identity; compression arrives later.
                self._emit(
                    active_run_id,
                    "prepare_next_turn.started",
                    {"turn_index": turn_index},
                )
                messages = self.prepare_next_turn(messages)
                self._emit(
                    active_run_id,
                    "prepare_next_turn.completed",
                    {"turn_index": turn_index, "message_count": len(messages)},
                )
                self._emit(active_run_id, "turn.completed", {"turn_index": turn_index})

            # At max turns, expose the last visible content and explicit stop reason.
            final_answer = messages[-1].content if messages else ""
            return self._complete(
                active_run_id,
                messages,
                final_answer,
                StopReason.MAX_TURNS,
            )
        except Exception as exc:
            # Unexpected failures are traced, then re-raised for caller visibility.
            self._emit(
                active_run_id,
                "run.failed",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
            raise

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        """Prepare the transcript before the next model turn.

        Args:
            messages: Current mutable transcript after tool observations.

        Returns:
            Transcript to expose to the next model call.
        """

        return messages

    def _complete(
        self,
        run_id: str,
        messages: list[KlaraMessage],
        final_answer: str,
        stop_reason: StopReason,
    ) -> KlaraRunResult:
        """Emit completion and build the final run result."""

        self._emit(run_id, "run.completed", {"stop_reason": stop_reason.value})
        return KlaraRunResult(
            run_id=run_id,
            messages=tuple(messages),
            final_answer=final_answer,
            stop_reason=stop_reason,
            hook_failures=tuple(self.hooks.failures),
        )

    def _emit(self, run_id: str, event_type: str, payload: dict[str, object]) -> None:
        """Create and emit one lifecycle event through the hook manager."""

        self.hooks.emit(KlaraEvent(type=event_type, run_id=run_id, payload=payload))
