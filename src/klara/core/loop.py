"""Core loop execution for Klara runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from klara.core.events import KlaraEvent
from klara.core.hooks import HookManager
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.policies import LoopPolicy, StopReason
from klara.core.tools import ToolRunner, ToolSpec


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


class FinalAnswerGuard(Protocol):
    """Protocol for context policy that can delay a final answer."""

    def apply(
        self,
        messages: tuple[KlaraMessage, ...],
    ) -> tuple[KlaraMessage, ...] | None:
        """Return replacement messages when the loop should continue."""

        ...


@dataclass(frozen=True)
class KlaraRunResult:
    """Final public result of one Klara loop execution."""

    # Run id joins the result with JSONL trace events.
    run_id: str
    # Messages preserve the final model-visible transcript for tests and replay.
    messages: tuple[KlaraMessage, ...]
    # Final answer is the user-facing assistant text produced by the model.
    final_answer: str
    # Stop reason makes loop termination explicit and testable.
    stop_reason: StopReason
    # Hook failures are visible without changing successful loop semantics.
    hook_failures: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class KlaraLoop:
    """Execute bounded model turns, tool observations, and lifecycle events.

    The loop owns runtime execution only. It does not choose persona, load
    memory, select capability profiles, query RAG, or talk to backend transports.
    Those concerns attach around the loop through harness, tools, hooks,
    context, or trace.
    """

    def __init__(
        self,
        *,
        llm: LlmClient,
        tool_executor: ToolRunner,
        hooks: HookManager | None = None,
        policy: LoopPolicy | None = None,
        model: str = "fake-model",
        system_prompt: str = "",
        final_answer_guard: FinalAnswerGuard | None = None,
    ) -> None:
        """Create a loop with injected model, tools, hooks, and policy.

        Args:
            llm: Model client used for each assistant turn.
            tool_executor: Executor for tools visible in this run.
            hooks: Optional hook manager for lifecycle events.
            policy: Optional stop/bounds policy.
            model: Model identifier passed through to the LLM client.
            system_prompt: Prompt assembled outside core by the harness.
            final_answer_guard: Optional context policy that can delay final
                answers by returning a guarded transcript.
        """

        # Dependencies are injected so core stays independent of providers/services.
        self.llm = llm
        self.tool_executor = tool_executor
        self.hooks = hooks or HookManager()
        self.policy = policy or LoopPolicy()
        self.model = model
        self.system_prompt = system_prompt
        self.final_answer_guard = final_answer_guard

    def run(
        self,
        user_input: str,
        *,
        run_id: str | None = None,
        prior_messages: tuple[KlaraMessage, ...] = (),
    ) -> KlaraRunResult:
        """Run the loop until final answer, max turns, or unexpected failure.

        Args:
            user_input: User message that starts this run.
            run_id: Optional stable id for deterministic traces and tests.
            prior_messages: Optional completed transcript before this user turn.

        Returns:
            A run result with final transcript, answer, stop reason, and hook
            failures.
        """

        # Active run id is the trace join key across all lifecycle events.
        active_run_id = run_id or str(uuid4())
        # Messages begin with optional app-provided history, then this user turn.
        messages: list[KlaraMessage] = [
            *prior_messages,
            KlaraMessage(role="user", content=user_input),
        ]
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

                if not response.tool_calls:
                    guarded_messages = self._apply_final_answer_guard(messages)
                    if guarded_messages is not None:
                        messages = guarded_messages
                        self._emit(
                            active_run_id,
                            "prepare_next_turn.started",
                            {"turn_index": turn_index, "guard": "final_answer"},
                        )
                        messages = self.prepare_next_turn(messages)
                        self._emit(
                            active_run_id,
                            "prepare_next_turn.completed",
                            {
                                "turn_index": turn_index,
                                "message_count": len(messages),
                                "guard": "final_answer",
                            },
                        )
                        self._emit(
                            active_run_id,
                            "turn.completed",
                            {"turn_index": turn_index, "guard": "final_answer"},
                        )
                        continue
                    messages.append(assistant_message)
                    # No tool calls means the assistant content is the final answer.
                    self._emit(active_run_id, "turn.completed", {"turn_index": turn_index})
                    return self._complete(
                        active_run_id,
                        messages,
                        response.content,
                        StopReason.FINAL,
                    )

                messages.append(assistant_message)

                # Execute every requested tool before preparing the next model turn.
                for call in response.tool_calls:
                    self._emit(
                        active_run_id,
                        "tool.started",
                        {"turn_index": turn_index, "tool_call": call.to_public_dict()},
                    )

                # Tool results become model-visible observations in request order.
                tool_results = self.tool_executor.execute_many(response.tool_calls)
                for result in tool_results:
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

                # Preparation stays as identity until context policy exists.
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

            # At max turns, stop exposing tools and ask for one final answer.
            return self._finalize_after_max_turns(active_run_id, messages)
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

    def _apply_final_answer_guard(
        self,
        messages: list[KlaraMessage],
    ) -> list[KlaraMessage] | None:
        """Return guarded messages when final answer policy needs another turn."""

        if self.final_answer_guard is None:
            return None
        guarded = self.final_answer_guard.apply(tuple(messages))
        if guarded is None:
            return None
        return list(guarded)

    def _finalize_after_max_turns(
        self,
        run_id: str,
        messages: list[KlaraMessage],
    ) -> KlaraRunResult:
        """Ask the model for a final no-tool answer after tool turns are exhausted."""

        final_turn_index = self.policy.max_turns + 1
        finalization_prompt = "\n\n".join(
            [
                self.system_prompt,
                (
                    "<finalization_context>\n"
                    "The tool turn limit has been reached. Do not request more tools. "
                    "Write the best final answer now from the observations already "
                    "in the transcript. If the observations are incomplete, say what "
                    "is uncertain.\n"
                    "</finalization_context>"
                ),
            ]
        ).strip()
        self._emit(
            run_id,
            "llm.started",
            {"turn_index": final_turn_index, "finalization": True},
        )
        response = self.llm.complete(
            system_prompt=finalization_prompt,
            messages=tuple(messages),
            tools=(),
            model=self.model,
        )
        ignored_tool_call_count = len(response.tool_calls)
        self._emit(
            run_id,
            "llm.completed",
            {
                "turn_index": final_turn_index,
                "tool_call_count": 0,
                "ignored_tool_call_count": ignored_tool_call_count,
                "usage": response.usage or {},
                "finalization": True,
            },
        )
        final_answer = response.content.strip()
        if not final_answer:
            final_answer = (
                "Tool turn limit reached before the model produced a final answer. "
                "Please ask again with a narrower request or fewer required lookups."
            )
        messages.append(KlaraMessage(role="assistant", content=final_answer))
        return self._complete(run_id, messages, final_answer, StopReason.MAX_TURNS)

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
