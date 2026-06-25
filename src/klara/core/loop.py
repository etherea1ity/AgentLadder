"""Core loop execution for Klara runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import re
from time import perf_counter
from typing import Any, Iterator, Protocol
from uuid import uuid4

from klara.core.events import EventKind, EventSequencer, KlaraEvent
from klara.core.hooks import (
    HookManager,
    PostToolUseContext,
    PreToolUseContext,
    StopContext,
    UserPromptSubmitContext,
)
from klara.core.messages import KlaraMessage, ModelResponse, ModelStreamEvent
from klara.core.policies import LoopPolicy, StopReason
from klara.core.tools import ToolCall, ToolResult, ToolRunner, ToolSpec


_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")
_ACTIVITY_TOOL_NAME = "update_activity"
_ACTIVITY_TOOL_SPEC = ToolSpec(
    name=_ACTIVITY_TOOL_NAME,
    description=(
        "Append Klara's public thinking update for the current step. "
        "Write only new progress that has not already been shown in "
        "<public_activity_so_far>. This is not the final answer."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Public thinking update to show before tool work.",
            }
        },
        "required": ["text"],
        "additionalProperties": False,
    },
)


class LlmClient(Protocol):
    """Protocol for any model client that can serve the Klara loop."""

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
        model: str,
        thinking_enabled: bool | None = None,
    ) -> ModelResponse:
        """Produce one assistant response for the current model-visible state.

        Args:
            system_prompt: Runtime prompt assembled by the harness.
            messages: Current transcript visible to the model.
            tools: Tool specs visible in this run.
            model: Model identifier selected by the harness.
            thinking_enabled: Optional per-run provider thinking switch.

        Returns:
            Assistant content plus optional tool calls.
        """

        ...


class StreamingLlmClient(LlmClient, Protocol):
    """Optional future protocol for provider streaming without changing loop users."""

    def stream_complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
        model: str,
        thinking_enabled: bool | None = None,
    ) -> Iterator[ModelStreamEvent]:
        """Yield provider reasoning/content/tool deltas and a final response."""

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


@dataclass
class _RunMetrics:
    """Accumulate public run-level metrics from lifecycle events."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    has_reported_tokens: bool = False

    def add_llm_metrics(self, metrics: dict[str, object]) -> None:
        """Accumulate one LLM metrics payload."""

        if metrics.get("token_source") == "reported":
            self.has_reported_tokens = True
        self.prompt_tokens += _int_token(metrics.get("prompt_tokens"))
        self.completion_tokens += _int_token(metrics.get("completion_tokens"))
        self.total_tokens += _int_token(metrics.get("total_tokens"))

    def to_public_dict(self, *, duration_ms: int) -> dict[str, object]:
        """Return run-level public metrics."""

        return {
            "duration_ms": duration_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "token_source": "reported" if self.has_reported_tokens else "unknown",
        }


@dataclass(frozen=True)
class _PreparedToolCalls:
    """Tool calls split into UI-only activity and executable runtime calls."""

    activity_text: str = ""
    external_calls: tuple[ToolCall, ...] = ()
    internal_activity_count: int = 0


@dataclass(frozen=True)
class FinalAnswerDecision:
    """Generic controller decision before accepting a no-tool assistant answer."""

    allowed: bool = True
    reason: str = ""
    feedback: str = ""


@dataclass(frozen=True)
class LoopControllerEvent:
    """Public trace event emitted by a loop controller through core hooks."""

    type: str
    payload: dict[str, object] = field(default_factory=dict)


class LoopController(Protocol):
    """Optional policy/context controller attached around the core loop."""

    def on_run_start(self, *, user_input: str, run_id: str) -> None:
        """Observe the start of one run."""

        ...

    def system_prompt_suffix(self) -> str:
        """Return extra model-visible runtime context for this turn."""

        ...

    def on_tool_results(self, *, results: tuple[ToolResult, ...]) -> None:
        """Observe tool results after execution."""

        ...

    def before_final_answer(self, *, content: str) -> FinalAnswerDecision:
        """Return whether a no-tool assistant answer may finalize the run."""

        ...

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        """Prepare the model-visible transcript for the next turn."""

        ...

    def drain_events(self) -> tuple[LoopControllerEvent, ...]:
        """Return pending public trace events from controller-owned state."""

        ...


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
        controllers: tuple[LoopController, ...] = (),
        model: str = "fake-model",
        thinking_enabled: bool | None = None,
        system_prompt: str = "",
    ) -> None:
        """Create a loop with injected model, tools, hooks, and policy.

        Args:
            llm: Model client used for each assistant turn.
            tool_executor: Executor for tools visible in this run.
            hooks: Optional hook manager for lifecycle events.
            policy: Optional stop/bounds policy.
            controllers: Optional runtime controllers around the loop.
            model: Model identifier passed through to the LLM client.
            thinking_enabled: Optional per-run provider thinking switch.
            system_prompt: Prompt assembled outside core by the harness.
        """

        # Dependencies are injected so core stays independent of providers/services.
        self.llm = llm
        self.tool_executor = tool_executor
        self.hooks = hooks or HookManager()
        self.policy = policy or LoopPolicy()
        self.controllers = controllers
        self.model = model
        self.thinking_enabled = thinking_enabled
        self.system_prompt = system_prompt

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
        final_block_signatures: dict[str, int] = {}
        public_activity_updates: list[str] = []
        run_started = perf_counter()
        run_metrics = _RunMetrics()
        self._emit(sequencer, active_run_id, EventKind.RUN_STARTED, {"model": self.model})
        for controller in self.controllers:
            controller.on_run_start(user_input=user_input, run_id=active_run_id)
        self._emit_controller_events(sequencer, active_run_id)
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
                    {
                        "turn_index": turn_index,
                        "model": self.model,
                        "thinking_enabled": self.thinking_enabled,
                    },
                )
                # Ask the injected model using only the prompt, transcript, and specs.
                llm_started = perf_counter()
                response = self.llm.complete(
                    system_prompt=self._system_prompt_for_turn(public_activity_updates),
                    messages=tuple(messages),
                    tools=_model_visible_tool_specs(self.tool_executor.specs),
                    model=self.model,
                    thinking_enabled=self.thinking_enabled,
                )
                prepared_calls = _prepare_tool_calls(response.tool_calls)
                activity_payload = _activity_payload(
                    response,
                    phase=_activity_phase(
                        turn_index=turn_index,
                        has_tool_calls=bool(prepared_calls.external_calls),
                    ),
                    tool_calls=prepared_calls.external_calls,
                    activity_tool_text=prepared_calls.activity_text,
                )
                llm_duration_ms = _duration_ms(llm_started)
                usage = _normalize_usage(response.usage)
                llm_metrics = _llm_metrics(llm_duration_ms, usage)
                run_metrics.add_llm_metrics(llm_metrics)
                self._emit(
                    sequencer,
                    active_run_id,
                    EventKind.LLM_COMPLETED,
                    {
                        "turn_index": turn_index,
                        "tool_call_count": len(prepared_calls.external_calls),
                        "internal_activity_call_count": prepared_calls.internal_activity_count,
                        "usage": usage,
                        "metrics": llm_metrics,
                        **_reasoning_payload(response),
                        **activity_payload,
                    },
                )
                activity_text = _activity_text_from_payload(activity_payload)
                if activity_text:
                    public_activity_updates.append(activity_text)
                # Store the assistant request before tools so replay matches transcript.
                assistant_message = KlaraMessage(
                    role="assistant",
                    content=_assistant_message_content(
                        response,
                        tool_calls=prepared_calls.external_calls,
                    ),
                    tool_calls=prepared_calls.external_calls,
                )

                if not prepared_calls.external_calls:
                    final_decision = self._before_final_answer(response.content)
                    self._emit_controller_events(sequencer, active_run_id)
                    if not final_decision.allowed:
                        block_signature = _final_decision_signature(final_decision)
                        block_count = final_block_signatures.get(block_signature, 0) + 1
                        final_block_signatures[block_signature] = block_count
                        if block_count >= self.policy.max_repeated_final_blocks:
                            policy_context = {
                                "reason": (
                                    "The same final-answer block repeated without "
                                    "new progress."
                                ),
                                "blocked_reason": final_decision.reason,
                                "repeated_count": block_count,
                            }
                            self._emit(
                                sequencer,
                                active_run_id,
                                "final_answer.no_progress_stopped",
                                {
                                    "turn_index": turn_index,
                                    **policy_context,
                                },
                            )
                            return self._finalize_without_tools(
                                sequencer,
                                active_run_id,
                                messages,
                                stop_reason=StopReason.NO_PROGRESS,
                                policy_context=policy_context,
                                run_started=run_started,
                                run_metrics=run_metrics,
                            )
                        feedback_message = _runtime_feedback_message(final_decision)
                        if feedback_message and _last_message_content(messages) != feedback_message:
                            messages.append(KlaraMessage(role="user", content=feedback_message))
                        self._emit(
                            sequencer,
                            active_run_id,
                            "final_answer.blocked",
                            {
                                "turn_index": turn_index,
                                "reason": final_decision.reason,
                                "feedback": final_decision.feedback,
                            },
                        )
                        self._emit(
                            sequencer,
                            active_run_id,
                            EventKind.TURN_COMPLETED,
                            {"turn_index": turn_index, "final_blocked": True},
                        )
                        continue
                    if self.controllers:
                        self._emit(
                            sequencer,
                            active_run_id,
                            "final_answer.allowed",
                            {
                                "turn_index": turn_index,
                                "reason": final_decision.reason,
                            },
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
                        run_started=run_started,
                        run_metrics=run_metrics,
                    )

                messages.append(assistant_message)

                tool_policy_stop = self._tool_policy_stop(
                    prepared_calls.external_calls,
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
                        run_started=run_started,
                        run_metrics=run_metrics,
                    )

                # Tool results become model-visible observations in request order.
                tool_results = self._execute_tool_calls(
                    sequencer,
                    active_run_id,
                    turn_index,
                    prepared_calls.external_calls,
                )
                for controller in self.controllers:
                    controller.on_tool_results(results=tool_results)
                self._emit_controller_events(sequencer, active_run_id)
                tool_call_count += len(prepared_calls.external_calls)
                for call in prepared_calls.external_calls:
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
                self._emit_controller_events(sequencer, active_run_id)
                self._emit(
                    sequencer,
                    active_run_id,
                    EventKind.PREPARE_NEXT_TURN_COMPLETED,
                    {"turn_index": turn_index, "message_count": len(messages)},
                )
                self._emit(sequencer, active_run_id, EventKind.TURN_COMPLETED, {"turn_index": turn_index})

            # At max turns, stop exposing tools and ask for one final answer.
            return self._finalize_after_max_turns(
                sequencer,
                active_run_id,
                messages,
                run_started=run_started,
                run_metrics=run_metrics,
            )
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

        prepared = messages
        for controller in self.controllers:
            prepared = controller.prepare_next_turn(prepared)
        return prepared

    def _finalize_after_max_turns(
        self,
        sequencer: EventSequencer,
        run_id: str,
        messages: list[KlaraMessage],
        *,
        run_started: float,
        run_metrics: _RunMetrics,
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
            run_started=run_started,
            run_metrics=run_metrics,
        )

    def _finalize_without_tools(
        self,
        sequencer: EventSequencer,
        run_id: str,
        messages: list[KlaraMessage],
        *,
        stop_reason: StopReason,
        policy_context: dict[str, object],
        run_started: float,
        run_metrics: _RunMetrics,
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
                self._system_prompt_for_turn(),
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
                "thinking_enabled": self.thinking_enabled,
            },
        )
        llm_started = perf_counter()
        response = self.llm.complete(
            system_prompt=finalization_prompt,
            messages=tuple(messages),
            tools=(),
            model=self.model,
            thinking_enabled=self.thinking_enabled,
        )
        llm_duration_ms = _duration_ms(llm_started)
        usage = _normalize_usage(response.usage)
        llm_metrics = _llm_metrics(llm_duration_ms, usage)
        run_metrics.add_llm_metrics(llm_metrics)
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
                    "usage": usage,
                    "metrics": llm_metrics,
                    "finalization": True,
                    **_reasoning_payload(response),
                    **_activity_payload(response, phase="finalizing"),
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
                    "thinking_enabled": self.thinking_enabled,
                    "retry_after_ignored_tools": True,
                },
            )
            llm_started = perf_counter()
            response = self.llm.complete(
                system_prompt=finalization_prompt,
                messages=tuple(messages),
                tools=(),
                model=self.model,
                thinking_enabled=self.thinking_enabled,
            )
            llm_duration_ms = _duration_ms(llm_started)
            usage = _normalize_usage(response.usage)
            llm_metrics = _llm_metrics(llm_duration_ms, usage)
            run_metrics.add_llm_metrics(llm_metrics)
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
                    "usage": usage,
                    "metrics": llm_metrics,
                    "finalization": True,
                    "retry_after_ignored_tools": True,
                    **_reasoning_payload(response),
                    **_activity_payload(response, phase="finalizing"),
                },
            )
        final_answer = response.content.strip()
        if not final_answer:
            final_answer = _empty_final_answer_for_stop(stop_reason)
        messages.append(KlaraMessage(role="assistant", content=final_answer))
        return self._complete(
            sequencer,
            run_id,
            messages,
            final_answer,
            stop_reason,
            run_started=run_started,
            run_metrics=run_metrics,
        )

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
            blocked_at = _now_iso()
            self._emit_tool_terminal(
                sequencer,
                run_id,
                turn_index,
                blocked_result,
                EventKind.TOOL_FAILED,
                blocked=True,
                duration_ms=0,
                started_at=blocked_at,
                completed_at=blocked_at,
            )

        for call in allowed_calls:
            self._emit(
                sequencer,
                run_id,
                EventKind.TOOL_STARTED,
                {
                    "turn_index": turn_index,
                    "tool_call": call.to_public_dict(),
                    "started_at": _now_iso(),
                },
            )

        executed_reports = self.tool_executor.execute_many_with_reports(
            tuple(allowed_calls)
        )
        executed_by_id: dict[str, ToolResult] = {}
        allowed_by_id = {call.id: call for call in allowed_calls}
        for report in executed_reports:
            result = report.result
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
                duration_ms=report.duration_ms,
                started_at=report.started_at,
                completed_at=report.completed_at,
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
        duration_ms: int,
        started_at: str,
        completed_at: str,
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
                "started_at": started_at,
                "completed_at": completed_at,
                "metrics": {
                    "duration_ms": duration_ms,
                },
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
        *,
        run_started: float,
        run_metrics: _RunMetrics,
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
            {
                "stop_reason": stop_reason.value,
                "metrics": run_metrics.to_public_dict(
                    duration_ms=_duration_ms(run_started)
                ),
            },
        )
        return KlaraRunResult(
            run_id=run_id,
            messages=tuple(messages),
            final_answer=final_answer,
            stop_reason=stop_reason,
            hook_failures=tuple(self.hooks.failures),
        )

    def _system_prompt_for_turn(
        self,
        public_activity_updates: list[str] | tuple[str, ...] = (),
    ) -> str:
        """Return base prompt plus controller context and same-run public activity."""

        prompt_parts = [self.system_prompt]
        activity_context = _public_activity_context(public_activity_updates)
        if activity_context:
            prompt_parts.append(activity_context)
        suffixes = [
            suffix.strip()
            for controller in self.controllers
            if (suffix := controller.system_prompt_suffix()).strip()
        ]
        prompt_parts.extend(suffixes)
        return "\n\n".join(part for part in prompt_parts if part.strip()).strip()

    def _before_final_answer(self, content: str) -> FinalAnswerDecision:
        """Aggregate controller decisions before finalization."""

        for controller in self.controllers:
            decision = controller.before_final_answer(content=content)
            if not decision.allowed:
                return decision
        return FinalAnswerDecision(allowed=True, reason="ready")

    def _emit_controller_events(
        self,
        sequencer: EventSequencer,
        run_id: str,
    ) -> None:
        """Emit pending controller-origin public events."""

        for controller in self.controllers:
            for event in controller.drain_events():
                self._emit(sequencer, run_id, event.type, event.payload)

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


def _duration_ms(started: float) -> int:
    """Return elapsed milliseconds from a perf_counter start value."""

    return max(0, int((perf_counter() - started) * 1000))


def _now_iso() -> str:
    """Return an ISO timestamp for public lifecycle timing payloads."""

    return datetime.now(UTC).isoformat()


def _normalize_usage(usage: dict[str, int] | None) -> dict[str, int | None]:
    """Normalize common provider usage field names."""

    source = usage or {}
    prompt = _int_or_none(_first_present(source, "prompt_tokens", "input_tokens"))
    completion = _int_or_none(
        _first_present(source, "completion_tokens", "output_tokens")
    )
    total = _int_or_none(_first_present(source, "total_tokens"))
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _llm_metrics(
    duration_ms: int,
    usage: dict[str, int | None],
) -> dict[str, object]:
    """Return public metrics for one LLM call."""

    token_source = (
        "reported"
        if any(usage.get(key) is not None for key in _TOKEN_KEYS)
        else "unknown"
    )
    return {
        "duration_ms": duration_ms,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "token_source": token_source,
    }


def _reasoning_payload(response: ModelResponse) -> dict[str, object]:
    """Return public provider reasoning metadata for UI projection."""

    summary = response.reasoning_summary
    if not isinstance(summary, str) or not summary.strip():
        return {}
    return {
        "reasoning": {
            "source": response.reasoning_source or "provider_reasoning",
            "summary": summary.strip(),
            "display": "summarized",
        }
    }


def _model_visible_tool_specs(specs: tuple[ToolSpec, ...]) -> tuple[ToolSpec, ...]:
    """Return external specs plus the internal public-activity control tool."""

    if not specs:
        return specs
    if any(spec.name == _ACTIVITY_TOOL_NAME for spec in specs):
        return specs
    return (*specs, _ACTIVITY_TOOL_SPEC)


def _prepare_tool_calls(calls: tuple[ToolCall, ...]) -> _PreparedToolCalls:
    """Separate UI-only public activity calls from executable tool calls."""

    activity_parts: list[str] = []
    external_calls: list[ToolCall] = []
    internal_count = 0
    for call in calls:
        if call.name == _ACTIVITY_TOOL_NAME:
            internal_count += 1
            text = _activity_text_from_call(call)
            if text:
                activity_parts.append(text)
            continue
        external_calls.append(call)
    return _PreparedToolCalls(
        activity_text="\n\n".join(activity_parts),
        external_calls=tuple(external_calls),
        internal_activity_count=internal_count,
    )


def _activity_text_from_call(call: ToolCall) -> str:
    """Return public activity text carried by the internal activity tool."""

    raw_text = call.arguments.get("text")
    return raw_text if isinstance(raw_text, str) else ""


def _activity_payload(
    response: ModelResponse,
    *,
    phase: str,
    tool_calls: tuple[ToolCall, ...] | None = None,
    activity_tool_text: str = "",
) -> dict[str, object]:
    """Return main-model public activity commentary for UI projection."""

    commentary = response.activity_commentary
    source = response.activity_source or "main_model_commentary"
    if not _has_text(commentary) and _has_text(activity_tool_text):
        commentary = activity_tool_text
        source = f"tool.{_ACTIVITY_TOOL_NAME}"
    has_tool_calls = bool(response.tool_calls if tool_calls is None else tool_calls)
    if has_tool_calls and not _has_text(commentary):
        commentary = response.content
        source = "assistant.content_with_tool_calls"
    text = _sanitize_public_activity(commentary)
    if not text:
        return {}
    return {
        "activity_commentary": {
            "text": text,
            "source": source,
            "phase": phase,
        }
    }


def _activity_text_from_payload(payload: dict[str, object]) -> str:
    """Return public activity text from an emitted LLM payload."""

    activity = payload.get("activity_commentary")
    if not isinstance(activity, dict):
        return ""
    text = activity.get("text")
    return text.strip() if isinstance(text, str) and text.strip() else ""


def _public_activity_context(updates: list[str] | tuple[str, ...]) -> str:
    """Return same-run public activity context for future model turns."""

    cleaned = [item.strip() for item in updates if item.strip()]
    if not cleaned:
        return ""
    body = "\n".join(f"{index}. {item}" for index, item in enumerate(cleaned, 1))
    return (
        "<public_activity_so_far>\n"
        f"{body}\n"
        "</public_activity_so_far>\n"
        "If you write another public activity update, add only new progress for "
        "the current step."
    )


def _assistant_message_content(
    response: ModelResponse,
    *,
    tool_calls: tuple[ToolCall, ...] | None = None,
) -> str:
    """Return model-visible assistant text for this response."""

    active_tool_calls = response.tool_calls if tool_calls is None else tool_calls
    if active_tool_calls:
        return ""
    return response.content


def _activity_phase(*, turn_index: int, has_tool_calls: bool) -> str:
    """Return a compact public phase label for activity commentary."""

    if not has_tool_calls:
        return "finalizing"
    return "before_tool" if turn_index == 1 else "between_tools"


def _sanitize_public_activity(value: object) -> str:
    """Return safe public commentary text without URLs or secret-shaped values."""

    if not isinstance(value, str):
        return ""
    text = _strip_internal_activity_labels(" ".join(value.split()))
    if not text:
        return ""
    lowered = text.lower()
    if any(
        term in lowered
        for term in (
            "chain-of-thought",
            "chain of thought",
            "hidden reasoning",
            "raw reasoning",
            "scratchpad",
            "raw payload",
            "api key",
            "secret",
            "password",
        )
    ):
        return ""
    text = re.sub(r"https?://\S+", "[url]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "sk-[redacted]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    return text


def _strip_internal_activity_labels(text: str) -> str:
    """Remove accidental public echoes of internal activity field labels."""

    pattern = (
        "(?i)\\b(?:update_activity(?:\\.text)?|activity_commentary|public_activity|"
        "assistant_activity(?:_delta)?)\\s*[:\\uff1a]\\s*"
    )
    return re.sub(pattern, "", text).strip()


def _has_text(value: object) -> bool:
    """Return whether a value is non-empty text."""

    return isinstance(value, str) and bool(value.strip())


def _first_present(source: dict[str, int], *keys: str) -> int | None:
    """Return the first present value from a usage dictionary."""

    for key in keys:
        if key in source:
            return source[key]
    return None


def _int_or_none(value: Any) -> int | None:
    """Return an integer only for real integer token counts."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _int_token(value: object) -> int:
    """Return a token count suitable for totals."""

    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


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


def _final_decision_signature(decision: FinalAnswerDecision) -> str:
    """Return a stable signature for repeated final-answer block detection."""

    return json.dumps(
        {
            "reason": decision.reason,
            "feedback": decision.feedback,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _runtime_feedback_message(decision: FinalAnswerDecision) -> str:
    """Return model-visible feedback after a controller blocks finalization."""

    feedback = decision.feedback.strip()
    if not feedback:
        return ""
    return (
        "<runtime_policy_feedback>\n"
        "The previous assistant draft was rejected by runtime policy and was not "
        "shown to the user. Continue the task from this feedback instead of "
        "repeating the rejected draft. If tools are available and the feedback "
        "asks for evidence, call the appropriate tool before answering.\n\n"
        f"{feedback}\n"
        "</runtime_policy_feedback>"
    )


def _last_message_content(messages: list[KlaraMessage]) -> str:
    """Return the last transcript content, or an empty string."""

    if not messages:
        return ""
    return messages[-1].content


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
    if stop_reason == StopReason.NO_PROGRESS:
        return (
            "The run stopped because no new progress was made. Please ask again "
            "with a narrower request or fewer required lookups."
        )
    return (
        "A tool policy limit was reached before the model produced a final answer. "
        "Please ask again with a narrower request or fewer required lookups."
    )
