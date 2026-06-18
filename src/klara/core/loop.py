"""Core loop execution for Klara runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Protocol
from uuid import uuid4

from klara.core.events import EventKind, EventSequencer, KlaraEvent
from klara.core.hooks import (
    HookManager,
    PostToolUseContext,
    PreToolUseContext,
    StopContext,
    UserPromptSubmitContext,
)
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.policies import LoopPolicy, StopReason
from klara.core.tools import ToolCall, ToolResult, ToolRunner, ToolSpec


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

    def fallback_answer(self, messages: tuple[KlaraMessage, ...]) -> str | None:
        """Return a safe final answer when repeated guards were ignored."""

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
        # Sequence numbers are scoped to this run for deterministic replay order.
        sequencer = EventSequencer()
        # Messages begin with optional app-provided history, then this user turn.
        messages: list[KlaraMessage] = [
            *prior_messages,
            KlaraMessage(role="user", content=user_input),
        ]
        tool_call_count = 0
        tool_call_signatures: dict[str, int] = {}
        self._emit(sequencer, active_run_id, EventKind.RUN_STARTED, {"model": self.model})
        self._emit(
            sequencer,
            active_run_id,
            EventKind.USER_PROMPT_SUBMIT_STARTED,
            {"input_length": len(user_input)},
        )
        user_prompt_decision = self.hooks.user_prompt_submit(
            UserPromptSubmitContext(run_id=active_run_id, user_input=user_input)
        )
        self._emit(
            sequencer,
            active_run_id,
            EventKind.USER_PROMPT_SUBMIT_COMPLETED,
            _decision_payload(user_prompt_decision),
        )

        try:
            # Iterate through bounded turns so a model cannot request tools forever.
            for turn_index in range(1, self.policy.max_turns + 1):
                self._emit(sequencer, active_run_id, EventKind.TURN_STARTED, {"turn_index": turn_index})
                self._emit(
                    sequencer,
                    active_run_id,
                    EventKind.LLM_STARTED,
                    {"turn_index": turn_index, "model": self.model},
                )
                # Ask the injected model using only the prompt, transcript, and specs.
                response = self.llm.complete(
                    system_prompt=self.system_prompt,
                    messages=tuple(messages),
                    tools=self.tool_executor.specs,
                    model=self.model,
                )
                self._emit(
                    sequencer,
                    active_run_id,
                    EventKind.LLM_COMPLETED,
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
                            sequencer,
                            active_run_id,
                            EventKind.PREPARE_NEXT_TURN_STARTED,
                            {"turn_index": turn_index, "guard": "final_answer"},
                        )
                        messages = self.prepare_next_turn(messages)
                        self._emit(
                            sequencer,
                            active_run_id,
                            EventKind.PREPARE_NEXT_TURN_COMPLETED,
                            {
                                "turn_index": turn_index,
                                "message_count": len(messages),
                                "guard": "final_answer",
                            },
                        )
                        self._emit(
                            sequencer,
                            active_run_id,
                            EventKind.TURN_COMPLETED,
                            {"turn_index": turn_index, "guard": "final_answer"},
                        )
                        continue
                    drafted_messages = [*messages, assistant_message]
                    guarded_messages = self._apply_final_answer_guard(drafted_messages)
                    if guarded_messages is not None:
                        messages = guarded_messages
                        self._emit(
                            sequencer,
                            active_run_id,
                            EventKind.PREPARE_NEXT_TURN_STARTED,
                            {"turn_index": turn_index, "guard": "final_answer"},
                        )
                        messages = self.prepare_next_turn(messages)
                        self._emit(
                            sequencer,
                            active_run_id,
                            EventKind.PREPARE_NEXT_TURN_COMPLETED,
                            {
                                "turn_index": turn_index,
                                "message_count": len(messages),
                                "guard": "final_answer",
                            },
                        )
                        self._emit(
                            sequencer,
                            active_run_id,
                            EventKind.TURN_COMPLETED,
                            {"turn_index": turn_index, "guard": "final_answer"},
                        )
                        continue
                    fallback_answer = self._fallback_final_answer(drafted_messages)
                    if fallback_answer is not None:
                        messages.append(
                            KlaraMessage(role="assistant", content=fallback_answer)
                        )
                        self._emit(
                            sequencer,
                            active_run_id,
                            EventKind.TURN_COMPLETED,
                            {
                                "turn_index": turn_index,
                                "guard": "fallback_answer",
                            },
                        )
                        return self._complete(
                            sequencer,
                            active_run_id,
                            messages,
                            fallback_answer,
                            StopReason.FINAL,
                        )
                    messages.append(assistant_message)
                    # No tool calls means the assistant content is the final answer.
                    self._emit(sequencer, active_run_id, EventKind.TURN_COMPLETED, {"turn_index": turn_index})
                    return self._complete(
                        sequencer,
                        active_run_id,
                        messages,
                        response.content,
                        StopReason.FINAL,
                    )

                messages.append(assistant_message)

                tool_policy_stop = self._tool_policy_stop(
                    response.tool_calls,
                    total_tool_calls=tool_call_count,
                    tool_call_signatures=tool_call_signatures,
                )
                if tool_policy_stop is not None:
                    stop_reason, policy_context = tool_policy_stop
                    self._emit(
                        sequencer,
                        active_run_id,
                        EventKind.TOOL_POLICY_STOPPED,
                        {
                            "turn_index": turn_index,
                            "stop_reason": stop_reason.value,
                            **policy_context,
                        },
                    )
                    return self._finalize_without_tools(
                        sequencer,
                        active_run_id,
                        messages,
                        stop_reason=stop_reason,
                        policy_context=policy_context,
                    )

                # Tool results become model-visible observations in request order.
                tool_results = self._execute_tool_calls(
                    sequencer,
                    active_run_id,
                    turn_index,
                    response.tool_calls,
                )
                tool_call_count += len(response.tool_calls)
                for call in response.tool_calls:
                    signature = _tool_call_signature(call)
                    tool_call_signatures[signature] = (
                        tool_call_signatures.get(signature, 0) + 1
                    )
                for result in tool_results:
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
                    sequencer,
                    active_run_id,
                    EventKind.PREPARE_NEXT_TURN_STARTED,
                    {"turn_index": turn_index},
                )
                messages = self.prepare_next_turn(messages)
                self._emit(
                    sequencer,
                    active_run_id,
                    EventKind.PREPARE_NEXT_TURN_COMPLETED,
                    {"turn_index": turn_index, "message_count": len(messages)},
                )
                self._emit(sequencer, active_run_id, EventKind.TURN_COMPLETED, {"turn_index": turn_index})

            # At max turns, stop exposing tools and ask for one final answer.
            return self._finalize_after_max_turns(sequencer, active_run_id, messages)
        except Exception as exc:
            # Unexpected failures are traced, then re-raised for caller visibility.
            self._emit(
                sequencer,
                active_run_id,
                EventKind.RUN_FAILED,
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

    def _fallback_final_answer(
        self,
        messages: list[KlaraMessage],
    ) -> str | None:
        """Return a guard-owned safe answer when available."""

        if self.final_answer_guard is None:
            return None
        fallback = getattr(self.final_answer_guard, "fallback_answer", None)
        if fallback is None:
            return None
        answer = fallback(tuple(messages))
        if answer is None or not answer.strip():
            return None
        return answer.strip()

    def _finalize_after_max_turns(
        self,
        sequencer: EventSequencer,
        run_id: str,
        messages: list[KlaraMessage],
    ) -> KlaraRunResult:
        """Ask the model for a final no-tool answer after tool turns are exhausted."""

        return self._finalize_without_tools(
            sequencer,
            run_id,
            messages,
            stop_reason=StopReason.MAX_TURNS,
            policy_context={
                "reason": "The tool turn limit has been reached.",
                "max_turns": self.policy.max_turns,
            },
        )

    def _finalize_without_tools(
        self,
        sequencer: EventSequencer,
        run_id: str,
        messages: list[KlaraMessage],
        *,
        stop_reason: StopReason,
        policy_context: dict[str, object],
    ) -> KlaraRunResult:
        """Ask the model for a final no-tool answer after a policy stop."""

        assistant_count = len(
            [message for message in messages if message.role == "assistant"]
        )
        final_turn_index = assistant_count + 1
        reason = str(
            policy_context.get("reason") or "A runtime policy limit was reached."
        )
        finalization_prompt = "\n\n".join(
            [
                self.system_prompt,
                (
                    "<finalization_context>\n"
                    f"{reason} Do not request more tools. "
                    "Write the best final answer now from the observations already "
                    "in the transcript. If the observations are incomplete, say what "
                    "is uncertain.\n"
                    "</finalization_context>"
                ),
            ]
        ).strip()
        self._emit(
            sequencer,
            run_id,
            EventKind.LLM_STARTED,
            {
                "turn_index": final_turn_index,
                "finalization": True,
                "model": self.model,
            },
        )
        response = self.llm.complete(
            system_prompt=finalization_prompt,
            messages=tuple(messages),
            tools=(),
            model=self.model,
        )
        ignored_tool_call_count = len(response.tool_calls)
        self._emit(
            sequencer,
            run_id,
            EventKind.LLM_COMPLETED,
            {
                "turn_index": final_turn_index,
                "tool_call_count": 0,
                "ignored_tool_call_count": ignored_tool_call_count,
                "stop_reason": stop_reason.value,
                "policy_context": policy_context,
                "usage": response.usage or {},
                "finalization": True,
            },
        )
        if not response.content.strip() and ignored_tool_call_count:
            retry_prompt = KlaraMessage(
                role="user",
                content=(
                    "<finalization_retry_guard>\n"
                    "Your previous finalization attempted to call tools, but "
                    "runtime policy has stopped tool use for this run. Tools "
                    "are unavailable now. Write the best final answer from the "
                    "observations already in the transcript. If evidence is "
                    "partial, say what is known and what remains uncertain.\n"
                    "</finalization_retry_guard>"
                ),
            )
            messages.append(retry_prompt)
            retry_turn_index = final_turn_index + 1
            self._emit(
                sequencer,
                run_id,
                EventKind.LLM_STARTED,
                {
                    "turn_index": retry_turn_index,
                    "finalization": True,
                    "model": self.model,
                    "retry_after_ignored_tools": True,
                },
            )
            response = self.llm.complete(
                system_prompt=finalization_prompt,
                messages=tuple(messages),
                tools=(),
                model=self.model,
            )
            ignored_tool_call_count = len(response.tool_calls)
            self._emit(
                sequencer,
                run_id,
                EventKind.LLM_COMPLETED,
                {
                    "turn_index": retry_turn_index,
                    "tool_call_count": 0,
                    "ignored_tool_call_count": ignored_tool_call_count,
                    "stop_reason": stop_reason.value,
                    "policy_context": policy_context,
                    "usage": response.usage or {},
                    "finalization": True,
                    "retry_after_ignored_tools": True,
                },
            )
        final_answer = response.content.strip()
        if not final_answer:
            final_answer = _empty_final_answer_for_stop(stop_reason)
        messages.append(KlaraMessage(role="assistant", content=final_answer))
        return self._complete(sequencer, run_id, messages, final_answer, stop_reason)

    def _tool_policy_stop(
        self,
        tool_calls: tuple[ToolCall, ...],
        *,
        total_tool_calls: int,
        tool_call_signatures: dict[str, int],
    ) -> tuple[StopReason, dict[str, object]] | None:
        """Return a policy stop when pending tools would exceed budgets."""

        pending_count = len(tool_calls)
        if total_tool_calls + pending_count > self.policy.max_tool_calls:
            return (
                StopReason.MAX_TOOL_CALLS,
                {
                    "reason": "The tool call budget has been reached.",
                    "max_tool_calls": self.policy.max_tool_calls,
                    "completed_tool_calls": total_tool_calls,
                    "pending_tool_calls": pending_count,
                },
            )

        pending_signatures = dict(tool_call_signatures)
        for call in tool_calls:
            signature = _tool_call_signature(call)
            next_count = pending_signatures.get(signature, 0) + 1
            pending_signatures[signature] = next_count
            if next_count > self.policy.max_repeated_tool_calls:
                return (
                    StopReason.REPEATED_TOOL_CALL,
                    {
                        "reason": "The same tool request repeated too many times.",
                        "tool_name": call.name,
                        "max_repeated_tool_calls": self.policy.max_repeated_tool_calls,
                        "repeated_count": next_count,
                    },
                )
        return None

    def _execute_tool_calls(
        self,
        sequencer: EventSequencer,
        run_id: str,
        turn_index: int,
        tool_calls: tuple[ToolCall, ...],
    ) -> tuple[ToolResult, ...]:
        """Run pre/post tool placements while preserving request-order results."""

        allowed_calls: list[ToolCall] = []
        blocked_results: dict[str, ToolResult] = {}
        for call in tool_calls:
            self._emit(
                sequencer,
                run_id,
                EventKind.PRE_TOOL_USE_STARTED,
                {"turn_index": turn_index, "tool_call": call.to_public_dict()},
            )
            decision = self.hooks.pre_tool_use(
                PreToolUseContext(
                    run_id=run_id,
                    turn_index=turn_index,
                    tool_call=call,
                )
            )
            completed_payload = {
                "turn_index": turn_index,
                "tool_call": call.to_public_dict(),
                **_decision_payload(decision),
            }
            self._emit(
                sequencer,
                run_id,
                EventKind.PRE_TOOL_USE_COMPLETED,
                completed_payload,
            )
            if decision.allowed:
                allowed_calls.append(call)
                continue
            blocked_result = _blocked_tool_result(call, decision.reason)
            blocked_results[call.id] = blocked_result
            self._emit_tool_terminal(
                sequencer,
                run_id,
                turn_index,
                blocked_result,
                EventKind.TOOL_FAILED,
                blocked=True,
            )

        for call in allowed_calls:
            self._emit(
                sequencer,
                run_id,
                EventKind.TOOL_STARTED,
                {"turn_index": turn_index, "tool_call": call.to_public_dict()},
            )

        executed_results = self.tool_executor.execute_many(tuple(allowed_calls))
        executed_by_id: dict[str, ToolResult] = {}
        allowed_by_id = {call.id: call for call in allowed_calls}
        for result in executed_results:
            terminal_kind = (
                EventKind.TOOL_COMPLETED if result.ok else EventKind.TOOL_FAILED
            )
            self._emit_tool_terminal(
                sequencer,
                run_id,
                turn_index,
                result,
                terminal_kind,
                blocked=False,
            )
            call = allowed_by_id.get(result.tool_call_id)
            if call is not None:
                self._emit_post_tool_use(
                    sequencer,
                    run_id,
                    turn_index,
                    call,
                    result,
                )
            executed_by_id[result.tool_call_id] = result

        ordered_results: list[ToolResult] = []
        for call in tool_calls:
            result = blocked_results.get(call.id) or executed_by_id[call.id]
            ordered_results.append(result)
        return tuple(ordered_results)

    def _emit_tool_terminal(
        self,
        sequencer: EventSequencer,
        run_id: str,
        turn_index: int,
        result: ToolResult,
        event_type: EventKind,
        *,
        blocked: bool,
    ) -> None:
        """Emit a tool terminal event with the public result payload."""

        self._emit(
            sequencer,
            run_id,
            event_type,
            {
                "turn_index": turn_index,
                "tool_result": result.to_public_dict(),
                "blocked": blocked,
            },
        )

    def _emit_post_tool_use(
        self,
        sequencer: EventSequencer,
        run_id: str,
        turn_index: int,
        call: ToolCall,
        result: ToolResult,
    ) -> None:
        """Emit and run post-tool placement hooks."""

        payload = {
            "turn_index": turn_index,
            "tool_call": call.to_public_dict(),
            "tool_result": result.to_public_dict(),
        }
        self._emit(sequencer, run_id, EventKind.POST_TOOL_USE_STARTED, payload)
        self.hooks.post_tool_use(
            PostToolUseContext(
                run_id=run_id,
                turn_index=turn_index,
                tool_call=call,
                tool_result=result,
            )
        )
        self._emit(sequencer, run_id, EventKind.POST_TOOL_USE_COMPLETED, payload)

    def _complete(
        self,
        sequencer: EventSequencer,
        run_id: str,
        messages: list[KlaraMessage],
        final_answer: str,
        stop_reason: StopReason,
    ) -> KlaraRunResult:
        """Emit completion and build the final run result."""

        self._emit(
            sequencer,
            run_id,
            EventKind.STOP_STARTED,
            {"stop_reason": stop_reason.value},
        )
        self.hooks.stop(StopContext(run_id=run_id, stop_reason=stop_reason.value))
        self._emit(
            sequencer,
            run_id,
            EventKind.STOP_COMPLETED,
            {"stop_reason": stop_reason.value},
        )
        self._emit(
            sequencer,
            run_id,
            EventKind.RUN_COMPLETED,
            {"stop_reason": stop_reason.value},
        )
        return KlaraRunResult(
            run_id=run_id,
            messages=tuple(messages),
            final_answer=final_answer,
            stop_reason=stop_reason,
            hook_failures=tuple(self.hooks.failures),
        )

    def _emit(
        self,
        sequencer: EventSequencer,
        run_id: str,
        event_type: str | EventKind,
        payload: dict[str, object],
    ) -> None:
        """Create and emit one lifecycle event through the hook manager."""

        self.hooks.emit(
            KlaraEvent(
                type=event_type,
                run_id=run_id,
                payload=payload,
                seq=sequencer.next(),
            )
        )


def _tool_call_signature(call: ToolCall) -> str:
    """Return a stable signature for repeated-call budget accounting."""

    arguments = json.dumps(
        call.arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"{call.name}:{arguments}"


def _blocked_tool_result(call: ToolCall, reason: str) -> ToolResult:
    """Return a model-visible observation for a hook-blocked tool."""

    public_reason = reason.strip() or "blocked"
    return ToolResult(
        tool_call_id=call.id,
        name=call.name,
        content="",
        ok=False,
        error=f"Tool blocked by hook: {public_reason}",
    )


def _decision_payload(decision: object) -> dict[str, object]:
    """Serialize a hook decision for public lifecycle events."""

    payload: dict[str, object] = {
        "allowed": bool(getattr(decision, "allowed", True)),
    }
    reason = str(getattr(decision, "reason", "") or "")
    public_metadata = dict(getattr(decision, "public_metadata", {}) or {})
    if reason:
        payload["reason"] = reason
    if public_metadata:
        payload["metadata"] = public_metadata
    return payload


def _empty_final_answer_for_stop(stop_reason: StopReason) -> str:
    """Return a user-facing fallback when finalization produces no text."""

    if stop_reason == StopReason.MAX_TURNS:
        return (
            "Tool turn limit reached before the model produced a final answer. "
            "Please ask again with a narrower request or fewer required lookups."
        )
    return (
        "A tool policy limit was reached before the model produced a final answer. "
        "Please ask again with a narrower request or fewer required lookups."
    )
