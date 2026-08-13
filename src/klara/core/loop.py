"""Core loop execution for Klara runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import re
from time import perf_counter
from typing import Any, Callable, Iterator, Protocol
from uuid import uuid4

from klara.core.events import EventKind, EventSequencer, KlaraEvent
from klara.core.hooks import (
    HookManager,
    PostToolUseContext,
    PreCompactContext,
    PreToolUseContext,
    StopContext,
    UserPromptSubmitContext,
)
from klara.core.messages import (
    KlaraMessage,
    LlmRuntimeEvent,
    ModelCallError,
    ModelResponse,
    ModelStreamEvent,
)
from klara.core.policies import LoopPolicy, StopReason
from klara.core.tools import ToolCall, ToolResult, ToolRunner, ToolSpec


_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")
_PUBLIC_LLM_RUNTIME_EVENTS = frozenset(
    {
        "provider.attempt_started",
        "provider.attempt_completed",
        "provider.attempt_failed",
        "provider.retry_scheduled",
        "model_route.candidate_started",
        "model_route.candidate_failed",
        "model_route.fallback_started",
        "model_route.candidate_completed",
    }
)
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
    replacement_content: str | None = None


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
            # Budget imported history before the first model call. Keeping this
            # inside the run boundary also traces controller or hook failures.
            messages = self._prepare_messages(
                sequencer,
                active_run_id,
                messages,
                turn_index=1,
                phase="initial_context",
            )
            self._emit_controller_events(sequencer, active_run_id)

            # Iterate through bounded turns so a model cannot request tools forever.
            for turn_index in range(1, self.policy.max_turns + 1):
                self._emit(sequencer, active_run_id, EventKind.TURN_STARTED, {"turn_index": turn_index})
                model_tools = _model_visible_tool_specs(self.tool_executor.specs)
                # Ask the injected model using only the prompt, transcript, and specs.
                response, messages, system_prompt, llm_duration_ms = (
                    self._complete_model_call(
                        sequencer,
                        active_run_id,
                        messages,
                        tools=model_tools,
                        turn_index=turn_index,
                        prompt_builder=lambda: self._system_prompt_for_turn(
                            public_activity_updates
                        ),
                        public_activity_updates=public_activity_updates,
                    )
                )
                model_messages = tuple(messages)
                prepared_calls = _prepare_tool_calls(response.tool_calls)
                activity_payload = _activity_payload(
                    response,
                    turn_index=turn_index,
                    phase=_activity_phase(
                        turn_index=turn_index,
                        has_tool_calls=bool(prepared_calls.external_calls),
                    ),
                    tool_calls=prepared_calls.external_calls,
                    activity_tool_text=prepared_calls.activity_text,
                )
                usage = _normalize_usage(response.usage)
                llm_metrics = _llm_metrics(llm_duration_ms, usage)
                run_metrics.add_llm_metrics(llm_metrics)
                self._emit(
                    sequencer,
                    active_run_id,
                    EventKind.LLM_COMPLETED,
                    {
                        "turn_index": turn_index,
                        "requested_model": self.model,
                        "model": response.model_used or self.model,
                        "tool_call_count": len(prepared_calls.external_calls),
                        "internal_activity_call_count": prepared_calls.internal_activity_count,
                        "usage": usage,
                        "metrics": llm_metrics,
                        "response_profile": _llm_response_profile(
                            response=response,
                            prepared_calls=prepared_calls,
                            activity_payload=activity_payload,
                        ),
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
                    if final_decision.allowed:
                        activity_only_decision = _activity_only_final_decision(
                            content=response.content,
                            activity_text=activity_text,
                        )
                        if activity_only_decision is not None:
                            final_decision = activity_only_decision
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
                        self._emit(
                            sequencer,
                            active_run_id,
                            EventKind.PREPARE_NEXT_TURN_STARTED,
                            {"turn_index": turn_index},
                        )
                        messages = self._prepare_messages(
                            sequencer,
                            active_run_id,
                            messages,
                            turn_index=turn_index + 1,
                            phase="after_final_block",
                        )
                        self._emit_controller_events(sequencer, active_run_id)
                        self._emit(
                            sequencer,
                            active_run_id,
                            EventKind.PREPARE_NEXT_TURN_COMPLETED,
                            {"turn_index": turn_index, "message_count": len(messages)},
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
                    final_content = (
                        final_decision.replacement_content
                        if final_decision.replacement_content is not None
                        else response.content
                    )
                    if final_content != response.content:
                        assistant_message = KlaraMessage(
                            role="assistant",
                            content=final_content,
                        )
                    messages.append(assistant_message)
                    # No tool calls means the assistant content is the final answer.
                    self._emit(sequencer, active_run_id, EventKind.TURN_COMPLETED, {"turn_index": turn_index})
                    return self._complete(
                        sequencer,
                        active_run_id,
                        messages,
                        final_content,
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
                messages = self._prepare_messages(
                    sequencer,
                    active_run_id,
                    messages,
                    turn_index=turn_index + 1,
                    phase="after_tools",
                )
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
            if isinstance(exc, ModelCallError):
                failure_payload: dict[str, object] = {
                    "error": "The model call failed.",
                    "error_code": exc.code,
                    "retryable": exc.retryable,
                    "status_code": exc.status_code,
                }
            else:
                failure_payload = {"error": f"{type(exc).__name__}: {exc}"}
            self._emit(
                sequencer,
                active_run_id,
                EventKind.RUN_FAILED,
                failure_payload,
            )
            raise

    def _complete_model_call(
        self,
        sequencer: EventSequencer,
        run_id: str,
        messages: list[KlaraMessage],
        *,
        tools: tuple[ToolSpec, ...],
        turn_index: int,
        prompt_builder: Callable[[], str],
        public_activity_updates: list[str] | tuple[str, ...] = (),
        finalization: bool = False,
        started_metadata: dict[str, object] | None = None,
    ) -> tuple[ModelResponse, list[KlaraMessage], str, int]:
        """Call the model with public retries and one bounded prompt recovery."""

        prepared = messages
        recovery_attempt = 0
        call_started = perf_counter()
        while True:
            system_prompt = prompt_builder()
            model_messages = tuple(prepared)
            self._emit(
                sequencer,
                run_id,
                EventKind.LLM_STARTED,
                {
                    "turn_index": turn_index,
                    "attempt": recovery_attempt + 1,
                    "prompt_recovery_attempt": recovery_attempt,
                    "finalization": finalization,
                    "model": self.model,
                    "thinking_enabled": self.thinking_enabled,
                    **(started_metadata or {}),
                    "input_profile": _llm_input_profile(
                        system_prompt=system_prompt,
                        messages=model_messages,
                        tools=tools,
                        public_activity_updates=public_activity_updates,
                        controller_count=len(self.controllers),
                        finalization=finalization,
                    ),
                },
            )
            attempt_started = perf_counter()
            try:
                response = self.llm.complete(
                    system_prompt=system_prompt,
                    messages=model_messages,
                    tools=tools,
                    model=self.model,
                    thinking_enabled=self.thinking_enabled,
                )
            except ModelCallError as exc:
                self._emit_llm_runtime_events(
                    sequencer,
                    run_id,
                    exc.runtime_events,
                    turn_index=turn_index,
                )
                self._emit(
                    sequencer,
                    run_id,
                    EventKind.MODEL_CALL_FAILED,
                    {
                        "turn_index": turn_index,
                        "attempt": recovery_attempt + 1,
                        "model": self.model,
                        "error_code": exc.code,
                        "retryable": exc.retryable,
                        "status_code": exc.status_code,
                        "duration_ms": _duration_ms(attempt_started),
                        "finalization": finalization,
                    },
                )
                if (
                    exc.code != "context_length_exceeded"
                    or recovery_attempt >= self.policy.max_prompt_recovery_attempts
                ):
                    raise
                next_attempt = recovery_attempt + 1
                recovered, handled = self._recover_prompt_too_long(
                    sequencer,
                    run_id,
                    prepared,
                    turn_index=turn_index,
                    attempt=next_attempt,
                )
                if not handled:
                    raise
                prepared = recovered
                recovery_attempt = next_attempt
                continue

            self._emit_llm_runtime_events(
                sequencer,
                run_id,
                response.runtime_events,
                turn_index=turn_index,
            )
            return response, prepared, system_prompt, _duration_ms(call_started)

    def _recover_prompt_too_long(
        self,
        sequencer: EventSequencer,
        run_id: str,
        messages: list[KlaraMessage],
        *,
        turn_index: int,
        attempt: int,
    ) -> tuple[list[KlaraMessage], bool]:
        """Run PreCompact and controller-owned forced prompt compaction."""

        recoverers = [
            recover
            for controller in self.controllers
            if callable(recover := getattr(controller, "recover_prompt_too_long", None))
        ]
        if not recoverers:
            return messages, False
        self._emit(
            sequencer,
            run_id,
            EventKind.PROMPT_RECOVERY_STARTED,
            {
                "turn_index": turn_index,
                "attempt": attempt,
                "messages_before": len(messages),
                "reason": "context_length_exceeded",
            },
        )
        compact_context = PreCompactContext(
            run_id=run_id,
            turn_index=turn_index,
            message_count=len(messages),
        )
        self._emit(
            sequencer,
            run_id,
            EventKind.PRE_COMPACT_STARTED,
            {
                "turn_index": turn_index,
                "message_count": len(messages),
                "phase": "provider_prompt_recovery",
                "attempt": attempt,
            },
        )
        self.hooks.pre_compact(compact_context)
        prepared = messages
        for recover in recoverers:
            prepared = recover(prepared, attempt=attempt)
        self._emit_controller_events(sequencer, run_id)
        self._emit(
            sequencer,
            run_id,
            EventKind.PRE_COMPACT_COMPLETED,
            {
                "turn_index": turn_index,
                "messages_before": len(messages),
                "messages_after": len(prepared),
                "phase": "provider_prompt_recovery",
                "attempt": attempt,
            },
        )
        self._emit(
            sequencer,
            run_id,
            EventKind.PROMPT_RECOVERY_COMPLETED,
            {
                "turn_index": turn_index,
                "attempt": attempt,
                "messages_before": len(messages),
                "messages_after": len(prepared),
            },
        )
        return prepared, True

    def _emit_llm_runtime_events(
        self,
        sequencer: EventSequencer,
        run_id: str,
        events: tuple[LlmRuntimeEvent, ...],
        *,
        turn_index: int,
    ) -> None:
        """Project only the public provider/router event contract into the trace."""

        for event in events:
            if event.type not in _PUBLIC_LLM_RUNTIME_EVENTS:
                continue
            self._emit(
                sequencer,
                run_id,
                event.type,
                {"turn_index": turn_index, **event.payload},
            )

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

    def _prepare_messages(
        self,
        sequencer: EventSequencer,
        run_id: str,
        messages: list[KlaraMessage],
        *,
        turn_index: int,
        phase: str,
    ) -> list[KlaraMessage]:
        """Run PreCompact placement when a controller reports budget pressure."""

        needs_compaction = any(
            bool(check(messages))
            for controller in self.controllers
            if callable(check := getattr(controller, "should_compact", None))
        )
        if needs_compaction:
            context = PreCompactContext(
                run_id=run_id,
                turn_index=turn_index,
                message_count=len(messages),
            )
            self._emit(
                sequencer,
                run_id,
                EventKind.PRE_COMPACT_STARTED,
                {"turn_index": turn_index, "message_count": len(messages), "phase": phase},
            )
            self.hooks.pre_compact(context)
        prepared = self.prepare_next_turn(messages)
        if needs_compaction:
            self._emit(
                sequencer,
                run_id,
                EventKind.PRE_COMPACT_COMPLETED,
                {
                    "turn_index": turn_index,
                    "messages_before": len(messages),
                    "messages_after": len(prepared),
                    "phase": phase,
                },
            )
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

        messages = self._prepare_messages(
            sequencer,
            run_id,
            messages,
            turn_index=len(
                [message for message in messages if message.role == "assistant"]
            )
            + 1,
            phase="before_finalization",
        )
        self._emit_controller_events(sequencer, run_id)
        assistant_count = len(
            [message for message in messages if message.role == "assistant"]
        )
        final_turn_index = assistant_count + 1
        reason = str(
            policy_context.get("reason") or "A runtime policy limit was reached."
        )
        finalization_context = (
            "<finalization_context>\n"
            f"{reason} Do not request more tools. "
            "Write the best final answer now from the observations already "
            "in the transcript. If the observations are incomplete, say what "
            "is uncertain.\n"
            "</finalization_context>"
        )

        def build_finalization_prompt() -> str:
            return "\n\n".join(
                [self._system_prompt_for_turn(), finalization_context]
            ).strip()

        response, messages, finalization_prompt, llm_duration_ms = (
            self._complete_model_call(
                sequencer,
                run_id,
                messages,
                tools=(),
                turn_index=final_turn_index,
                prompt_builder=build_finalization_prompt,
                finalization=True,
            )
        )
        model_messages = tuple(messages)
        usage = _normalize_usage(response.usage)
        llm_metrics = _llm_metrics(llm_duration_ms, usage)
        run_metrics.add_llm_metrics(llm_metrics)
        ignored_tool_call_count = len(response.tool_calls)
        prepared_calls = _prepare_tool_calls(response.tool_calls)
        activity_payload = _activity_payload(
            response,
            turn_index=final_turn_index,
            phase="finalizing",
        )
        self._emit(
            sequencer,
            run_id,
            EventKind.LLM_COMPLETED,
            {
                "turn_index": final_turn_index,
                "requested_model": self.model,
                "model": response.model_used or self.model,
                "tool_call_count": 0,
                "ignored_tool_call_count": ignored_tool_call_count,
                "stop_reason": stop_reason.value,
                "policy_context": policy_context,
                "usage": usage,
                "metrics": llm_metrics,
                "finalization": True,
                "response_profile": _llm_response_profile(
                    response=response,
                    prepared_calls=prepared_calls,
                    activity_payload=activity_payload,
                ),
                **_reasoning_payload(response),
                **activity_payload,
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
            retry_messages = tuple(messages)
            response, messages, finalization_prompt, llm_duration_ms = (
                self._complete_model_call(
                    sequencer,
                    run_id,
                    list(retry_messages),
                    tools=(),
                    turn_index=retry_turn_index,
                    prompt_builder=build_finalization_prompt,
                    finalization=True,
                    started_metadata={"retry_after_ignored_tools": True},
                )
            )
            usage = _normalize_usage(response.usage)
            llm_metrics = _llm_metrics(llm_duration_ms, usage)
            run_metrics.add_llm_metrics(llm_metrics)
            ignored_tool_call_count = len(response.tool_calls)
            prepared_calls = _prepare_tool_calls(response.tool_calls)
            activity_payload = _activity_payload(
                response,
                turn_index=retry_turn_index,
                phase="finalizing",
            )
            self._emit(
                sequencer,
                run_id,
                EventKind.LLM_COMPLETED,
                {
                    "turn_index": retry_turn_index,
                    "requested_model": self.model,
                    "model": response.model_used or self.model,
                    "tool_call_count": 0,
                    "ignored_tool_call_count": ignored_tool_call_count,
                    "stop_reason": stop_reason.value,
                    "policy_context": policy_context,
                    "usage": usage,
                    "metrics": llm_metrics,
                    "finalization": True,
                    "retry_after_ignored_tools": True,
                    "response_profile": _llm_response_profile(
                        response=response,
                        prepared_calls=prepared_calls,
                        activity_payload=activity_payload,
                    ),
                    **_reasoning_payload(response),
                    **activity_payload,
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

        candidate_content = content
        replacement_content: str | None = None
        reasons: list[str] = []
        for controller in self.controllers:
            decision = controller.before_final_answer(content=candidate_content)
            if not decision.allowed:
                return decision
            if decision.reason:
                reasons.append(decision.reason)
            if decision.replacement_content is not None:
                candidate_content = decision.replacement_content
                replacement_content = decision.replacement_content
        return FinalAnswerDecision(
            allowed=True,
            reason=",".join(dict.fromkeys(reasons)) or "ready",
            replacement_content=replacement_content,
        )

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


def _llm_input_profile(
    *,
    system_prompt: str,
    messages: tuple[KlaraMessage, ...],
    tools: tuple[ToolSpec, ...],
    public_activity_updates: list[str] | tuple[str, ...],
    controller_count: int,
    finalization: bool = False,
) -> dict[str, object]:
    """Return trace-safe metadata for one model-visible request boundary."""

    role_counts: dict[str, int] = {}
    total_content_chars = 0
    tool_result_count = 0
    assistant_tool_call_message_count = 0
    for message in messages:
        role_counts[message.role] = role_counts.get(message.role, 0) + 1
        total_content_chars += len(message.content)
        if message.role == "tool":
            tool_result_count += 1
        if message.tool_calls:
            assistant_tool_call_message_count += 1

    last_message = messages[-1] if messages else None
    tool_names = [tool.name for tool in tools]
    tool_spec_fingerprint = _stable_fingerprint(
        [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]
    )
    return {
        "message_count": len(messages),
        "role_counts": role_counts,
        "total_content_chars": total_content_chars,
        "last_message_role": last_message.role if last_message else None,
        "last_message_chars": len(last_message.content) if last_message else 0,
        "tool_result_count": tool_result_count,
        "assistant_tool_call_message_count": assistant_tool_call_message_count,
        "system_prompt_chars": len(system_prompt),
        "system_prompt_hash": _stable_fingerprint(system_prompt),
        "tool_spec_count": len(tools),
        "tool_names": tool_names,
        "tool_spec_hash": tool_spec_fingerprint,
        "public_activity_update_count": len(public_activity_updates),
        "controller_count": controller_count,
        "finalization": finalization,
    }


def _llm_response_profile(
    *,
    response: ModelResponse,
    prepared_calls: _PreparedToolCalls,
    activity_payload: dict[str, object],
) -> dict[str, object]:
    """Return trace-safe metadata for one model response boundary."""

    activity_text = _activity_text_from_payload(activity_payload)
    reasoning_text = (
        response.reasoning_summary.strip()
        if isinstance(response.reasoning_summary, str)
        else ""
    )
    return {
        "content_chars": len(response.content),
        "has_content": bool(response.content.strip()),
        "external_tool_call_count": len(prepared_calls.external_calls),
        "internal_activity_call_count": prepared_calls.internal_activity_count,
        "tool_call_names": [call.name for call in prepared_calls.external_calls],
        "tool_call_ids": [call.id for call in prepared_calls.external_calls],
        "has_activity_commentary": bool(activity_text),
        "activity_commentary_chars": len(activity_text),
        "has_provider_reasoning": bool(reasoning_text),
        "provider_reasoning_chars": len(reasoning_text),
    }


def _stable_fingerprint(value: object) -> str:
    """Return a short stable hash for trace joins without exposing raw content."""

    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


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
    turn_index: int,
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
            "activity_id": f"activity_turn_{turn_index}",
            "sequence": turn_index,
            "status": "completed",
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


def _activity_only_final_decision(
    *,
    content: str,
    activity_text: str,
) -> FinalAnswerDecision | None:
    """Reject activity-only no-tool turns because activity is not final answer."""

    if content.strip() or not activity_text.strip():
        return None
    return FinalAnswerDecision(
        allowed=False,
        reason="activity_without_final_answer",
        feedback=(
            "The previous assistant turn only emitted public activity/thinking, "
            "not a final answer. Write the final answer for the user now from "
            "the available observations. Do not repeat the public activity "
            "update. Call a tool only if more evidence is still required."
        ),
    )


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
