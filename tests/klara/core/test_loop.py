from __future__ import annotations

from dataclasses import dataclass

from klara.core.hooks import (
    HookDecision,
    HookManager,
    PostToolUseContext,
    PreToolUseContext,
)
from klara.core.loop import FinalAnswerDecision, KlaraLoop, LoopControllerEvent
from klara.core.messages import KlaraMessage, ModelResponse, ModelStreamEvent
from klara.core.policies import LoopPolicy, StopReason
from klara.core.tools import JsonObject, ToolCall, ToolMetadata, ToolResult, ToolSpec
from klara.tools.base import BaseTool
from klara.tools.executor import ToolExecutor


@dataclass(frozen=True)
class EchoFixtureTool(BaseTool):
    """Test-only echo fixture for proving loop tool observations."""

    spec: ToolSpec = ToolSpec(
        name="test_echo",
        description="Echo text for tests.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(label="Test Echo", category="test")

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return the requested text as a tool observation."""

        return self.success(arguments, str(arguments.get("text", "")))


@dataclass(frozen=True)
class ExplodingFixtureTool(BaseTool):
    """Test-only tool that raises to exercise terminal failure events."""

    spec: ToolSpec = ToolSpec(
        name="test_explode",
        description="Raise an exception for tests.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": True},
    )
    metadata: ToolMetadata = ToolMetadata(label="Explode", category="test")

    def run(self, arguments: JsonObject) -> ToolResult:
        """Raise instead of returning a normal observation."""

        raise RuntimeError("boom")


class ScriptedLlm:
    """Fake LLM that returns pre-scripted responses in call order."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        """Store scripted responses and model-call observations for assertions."""

        # Responses are consumed so tests can prove turn ordering.
        self.responses = responses
        # Calls keep the model-visible transcript and tool specs per turn.
        self.calls: list[tuple[tuple[KlaraMessage, ...], tuple[ToolSpec, ...]]] = []
        # System prompts prove finalization can add no-tool guidance.
        self.system_prompts: list[str] = []

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
        model: str,
    ) -> ModelResponse:
        """Return the next scripted model response."""

        # Capture each call before popping so failure cases still expose evidence.
        self.system_prompts.append(system_prompt)
        self.calls.append((messages, tools))
        if not self.responses:
            raise AssertionError("No scripted LLM response left")
        return self.responses.pop(0)


class FakeStreamingLlm(ScriptedLlm):
    """Fake client that exposes the reserved streaming protocol surface."""

    def stream_complete(self, **_: object):
        """Yield one provider reasoning delta and a terminal response."""

        response = ModelResponse(content="streamed final")
        yield ModelStreamEvent(
            type="provider_reasoning_delta",
            delta="provider-visible reasoning summary",
        )
        yield ModelStreamEvent(type="completed", response=response)


class EventRecorder:
    """Hook that records public lifecycle events."""

    def __init__(self) -> None:
        """Create empty event storage."""

        self.events: list[object] = []
        self.event_types: list[str] = []

    def on_event(self, event: object) -> None:
        """Record one public event type."""

        self.events.append(event)
        self.event_types.append(str(getattr(event, "type")))


class BlockingFinalController:
    """Test controller that rejects the first no-tool final answer."""

    def __init__(self) -> None:
        """Create controller state for assertions."""

        self.started = False
        self.block_count = 0
        self.events = [LoopControllerEvent(type="controller.started", payload={})]

    def on_run_start(self, *, user_input: str, run_id: str) -> None:
        """Record that the controller saw run start."""

        self.started = True

    def system_prompt_suffix(self) -> str:
        """Expose feedback after blocking a final answer."""

        if self.block_count:
            return "<controller_feedback>continue after blocked final</controller_feedback>"
        return ""

    def on_tool_results(self, *, results: tuple[ToolResult, ...]) -> None:
        """No-op for this integration test."""

    def before_final_answer(self, *, content: str) -> FinalAnswerDecision:
        """Block exactly the first final answer."""

        if self.block_count == 0:
            self.block_count += 1
            return FinalAnswerDecision(
                allowed=False,
                reason="not_ready",
                feedback="Need another model turn.",
            )
        return FinalAnswerDecision(allowed=True, reason="ready")

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        """No-op transcript preparation."""

        return messages

    def drain_events(self) -> tuple[LoopControllerEvent, ...]:
        """Return queued controller events."""

        events = tuple(self.events)
        self.events.clear()
        return events


class BlockingPreToolHook:
    """Hook that blocks one tool before execution."""

    def __init__(self, reason: str = "blocked for test") -> None:
        """Store the public block reason."""

        self.reason = reason
        self.contexts: list[PreToolUseContext] = []

    def on_event(self, event: object) -> None:
        """Observer method is not needed for this test hook."""

    def on_pre_tool_use(self, context: PreToolUseContext) -> HookDecision:
        """Block every requested tool."""

        self.contexts.append(context)
        return HookDecision(allowed=False, reason=self.reason)


class PostToolRecordingHook:
    """Hook that records post-tool contexts."""

    def __init__(self) -> None:
        """Create empty context storage."""

        self.contexts: list[PostToolUseContext] = []

    def on_event(self, event: object) -> None:
        """Observer method is not needed for this test hook."""

    def on_post_tool_use(self, context: PostToolUseContext) -> None:
        """Record the post-tool observation."""

        self.contexts.append(context)


class BrokenPreToolHook:
    """Hook whose pre-tool placement fails."""

    def on_event(self, event: object) -> None:
        """Observer method is not needed for this test hook."""

    def on_pre_tool_use(self, context: PreToolUseContext) -> HookDecision:
        """Raise so HookManager can prove safe default allow."""

        raise RuntimeError("pre broke")


class SpyToolExecutor(ToolExecutor):
    """Tool executor that counts actual single-call executions."""

    def __init__(self, tools: list[BaseTool] | None = None) -> None:
        """Create a spy executor with an execution counter."""

        super().__init__(tools)
        self.execute_calls = 0

    def execute(self, call: ToolCall) -> ToolResult:
        """Count concrete executions before delegating."""

        self.execute_calls += 1
        return super().execute(call)


def _tool_call_ids_for(events: list[object], event_type: str) -> list[str]:
    """Return tool call ids from public tool lifecycle events."""

    ids: list[str] = []
    for event in events:
        if str(getattr(event, "type")) != event_type:
            continue
        payload = getattr(event, "payload")
        if event_type == "tool.started":
            ids.append(str(payload["tool_call"]["id"]))
        else:
            ids.append(str(payload["tool_result"]["tool_call_id"]))
    return ids


def _terminal_tool_call_ids(events: list[object]) -> list[str]:
    """Return tool call ids from terminal tool lifecycle events."""

    ids: list[str] = []
    ids.extend(_tool_call_ids_for(events, "tool.completed"))
    ids.extend(_tool_call_ids_for(events, "tool.failed"))
    return ids


def test_no_tool_run_returns_final_answer() -> None:
    llm = ScriptedLlm([ModelResponse(content="Hello from Klara.")])
    loop = KlaraLoop(llm=llm, tool_executor=ToolExecutor())

    result = loop.run("hi", run_id="run-no-tool")

    assert result.final_answer == "Hello from Klara."
    assert result.stop_reason == StopReason.FINAL
    assert [message.role for message in result.messages] == ["user", "assistant"]


def test_controller_can_block_premature_no_tool_final_answer() -> None:
    recorder = EventRecorder()
    controller = BlockingFinalController()
    llm = ScriptedLlm(
        [
            ModelResponse(content="premature final"),
            ModelResponse(content="final after feedback"),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor(),
        hooks=HookManager([recorder]),
        controllers=(controller,),
    )

    result = loop.run("latest information please", run_id="run-controller")

    assert controller.started is True
    assert result.final_answer == "final after feedback"
    assert result.messages[0].content == "latest information please"
    assert result.messages[1].role == "user"
    assert "<runtime_policy_feedback>" in result.messages[1].content
    assert "Need another model turn." in result.messages[1].content
    assert result.messages[2].content == "final after feedback"
    assert "premature final" not in [message.content for message in result.messages]
    assert "final_answer.blocked" in recorder.event_types
    assert "controller.started" in recorder.event_types
    assert "<controller_feedback>" in llm.system_prompts[1]
    assert "<runtime_policy_feedback>" in llm.calls[1][0][-1].content


def test_streaming_protocol_can_represent_provider_reasoning_delta() -> None:
    client = FakeStreamingLlm([ModelResponse(content="unused")])

    events = tuple(client.stream_complete())

    assert events[0].type == "provider_reasoning_delta"
    assert events[0].delta == "provider-visible reasoning summary"
    assert events[1].type == "completed"
    assert events[1].response is not None
    assert events[1].response.content == "streamed final"


def test_llm_completed_event_includes_duration_ms() -> None:
    recorder = EventRecorder()
    llm = ScriptedLlm(
        [ModelResponse(content="done", usage={"input_tokens": 2, "output_tokens": 3})]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor(),
        hooks=HookManager([recorder]),
    )

    loop.run("hi", run_id="run-llm-metrics")

    completed = next(
        event for event in recorder.events if str(getattr(event, "type")) == "llm.completed"
    )
    metrics = getattr(completed, "payload")["metrics"]
    usage = getattr(completed, "payload")["usage"]
    assert isinstance(metrics["duration_ms"], int)
    assert metrics["duration_ms"] >= 0
    assert metrics["prompt_tokens"] == 2
    assert metrics["completion_tokens"] == 3
    assert metrics["total_tokens"] == 5
    assert metrics["token_source"] == "reported"
    assert usage["prompt_tokens"] == 2
    assert usage["completion_tokens"] == 3


def test_tool_terminal_event_includes_duration_ms() -> None:
    recorder = EventRecorder()
    tool_call = ToolCall(
        id="call-1",
        name="test_echo",
        arguments={"text": "observed"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(tool_call,)),
            ModelResponse(content="done"),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        hooks=HookManager([recorder]),
    )

    loop.run("echo", run_id="run-tool-metrics")

    completed = next(
        event
        for event in recorder.events
        if str(getattr(event, "type")) == "tool.completed"
    )
    metrics = getattr(completed, "payload")["metrics"]
    assert isinstance(metrics["duration_ms"], int)
    assert metrics["duration_ms"] >= 0


def test_run_completed_event_includes_metrics() -> None:
    recorder = EventRecorder()
    llm = ScriptedLlm(
        [ModelResponse(content="done", usage={"prompt_tokens": 4, "completion_tokens": 6})]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor(),
        hooks=HookManager([recorder]),
    )

    loop.run("hi", run_id="run-completed-metrics")

    completed = next(
        event for event in recorder.events if str(getattr(event, "type")) == "run.completed"
    )
    metrics = getattr(completed, "payload")["metrics"]
    assert isinstance(metrics["duration_ms"], int)
    assert metrics["duration_ms"] >= 0
    assert metrics["prompt_tokens"] == 4
    assert metrics["completion_tokens"] == 6
    assert metrics["total_tokens"] == 10
    assert metrics["token_source"] == "reported"


def test_run_can_start_with_prior_conversation_messages() -> None:
    llm = ScriptedLlm([ModelResponse(content="I can continue.")])
    loop = KlaraLoop(llm=llm, tool_executor=ToolExecutor())

    result = loop.run(
        "continue",
        run_id="run-history",
        prior_messages=(
            KlaraMessage(role="user", content="draw Klara"),
            KlaraMessage(role="assistant", content="I can make that image."),
        ),
    )

    assert result.final_answer == "I can continue."
    assert [message.role for message in llm.calls[0][0]] == [
        "user",
        "assistant",
        "user",
    ]
    assert llm.calls[0][0][-1].content == "continue"


def test_one_tool_run_feeds_observation_back_to_llm() -> None:
    tool_call = ToolCall(
        id="call-1",
        name="test_echo",
        arguments={"text": "observed"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(tool_call,)),
            ModelResponse(content="I saw observed."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
    )

    result = loop.run("use a tool", run_id="run-tool")

    assert result.final_answer == "I saw observed."
    assert result.stop_reason == StopReason.FINAL
    assert [message.role for message in result.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert llm.calls[1][0][-1].role == "tool"
    assert llm.calls[1][0][-1].content == "observed"


def test_tool_call_content_becomes_public_activity_not_history() -> None:
    recorder = EventRecorder()
    tool_call = ToolCall(
        id="call-activity",
        name="test_echo",
        arguments={"text": "observed"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(
                content="I will check the tool first.",
                tool_calls=(tool_call,),
            ),
            ModelResponse(content="I saw observed."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        hooks=HookManager([recorder]),
    )

    result = loop.run("use a tool", run_id="run-tool-activity")

    activity = next(
        event
        for event in recorder.events
        if str(getattr(event, "type")) == "llm.completed"
    )
    assert getattr(activity, "payload")["activity_commentary"]["text"] == (
        "I will check the tool first."
    )
    assert result.final_answer == "I saw observed."
    assert result.messages[1].role == "assistant"
    assert result.messages[1].content == ""
    assert all(
        "I will check the tool first." not in message.content
        for message in llm.calls[1][0]
    )


def test_empty_tool_call_content_does_not_create_public_activity() -> None:
    recorder = EventRecorder()
    tool_call = ToolCall(
        id="call-empty-activity",
        name="test_echo",
        arguments={"text": "observed"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(tool_call,)),
            ModelResponse(content="I saw observed."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        hooks=HookManager([recorder]),
    )

    loop.run("use a tool", run_id="run-empty-tool-activity")

    llm_completed = next(
        event
        for event in recorder.events
        if str(getattr(event, "type")) == "llm.completed"
    )
    assert "activity_commentary" not in getattr(llm_completed, "payload")


def test_structured_activity_commentary_emits_without_replacing_final_answer() -> None:
    recorder = EventRecorder()
    llm = ScriptedLlm(
        [
            ModelResponse(
                content="Final answer.",
                activity_commentary="I will keep this as public activity.",
                activity_source="message.activity_commentary",
            )
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor(),
        hooks=HookManager([recorder]),
    )

    result = loop.run("answer", run_id="run-structured-activity")

    llm_completed = next(
        event
        for event in recorder.events
        if str(getattr(event, "type")) == "llm.completed"
    )
    assert result.final_answer == "Final answer."
    assert result.messages[-1].content == "Final answer."
    assert (
        getattr(llm_completed, "payload")["activity_commentary"]["text"]
        == "I will keep this as public activity."
    )


def test_pre_tool_use_defaults_to_allow() -> None:
    recorder = EventRecorder()
    hooks = HookManager([recorder])
    tool_call = ToolCall(
        id="call-allow",
        name="test_echo",
        arguments={"text": "allowed"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(tool_call,)),
            ModelResponse(content="I saw allowed."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        hooks=hooks,
    )

    result = loop.run("use a tool", run_id="run-pre-allow")

    assert result.final_answer == "I saw allowed."
    assert "pre_tool_use.started" in recorder.event_types
    assert "pre_tool_use.completed" in recorder.event_types
    assert _tool_call_ids_for(recorder.events, "tool.started") == ["call-allow"]
    assert _tool_call_ids_for(recorder.events, "tool.completed") == ["call-allow"]
    assert _terminal_tool_call_ids(recorder.events) == ["call-allow"]
    assert result.messages[2].content == "allowed"


def test_parallel_tool_batch_pairs_each_call_independently() -> None:
    recorder = EventRecorder()
    first_call = ToolCall(
        id="call-parallel-1",
        name="test_echo",
        arguments={"text": "one"},
    )
    second_call = ToolCall(
        id="call-parallel-2",
        name="test_echo",
        arguments={"text": "two"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(first_call, second_call)),
            ModelResponse(content="done"),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        hooks=HookManager([recorder]),
    )

    result = loop.run("use two tools", run_id="run-parallel-tools")

    assert [message.content for message in result.messages if message.role == "tool"] == [
        "one",
        "two",
    ]
    assert _tool_call_ids_for(recorder.events, "tool.started") == [
        "call-parallel-1",
        "call-parallel-2",
    ]
    assert _tool_call_ids_for(recorder.events, "tool.completed") == [
        "call-parallel-1",
        "call-parallel-2",
    ]
    assert _terminal_tool_call_ids(recorder.events) == [
        "call-parallel-1",
        "call-parallel-2",
    ]


def test_pre_tool_use_can_block_tool_with_model_visible_observation() -> None:
    tool_call = ToolCall(
        id="call-blocked",
        name="test_echo",
        arguments={"text": "should not run"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(tool_call,)),
            ModelResponse(content="I saw the block."),
        ]
    )
    hook = BlockingPreToolHook(reason="test policy")
    executor = SpyToolExecutor([EchoFixtureTool()])
    loop = KlaraLoop(
        llm=llm,
        tool_executor=executor,
        hooks=HookManager([hook]),
    )

    result = loop.run("use a blocked tool", run_id="run-pre-block")

    assert executor.execute_calls == 0
    assert result.messages[2].role == "tool"
    assert result.messages[2].content == "Tool blocked by hook: test policy"
    assert llm.calls[1][0][-1].content == "Tool blocked by hook: test policy"
    assert hook.contexts[0].tool_call.id == "call-blocked"


def test_blocked_tool_emits_failed_terminal_without_started_event() -> None:
    recorder = EventRecorder()
    tool_call = ToolCall(
        id="call-blocked",
        name="test_echo",
        arguments={"text": "should not run"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(tool_call,)),
            ModelResponse(content="blocked"),
        ]
    )
    hooks = HookManager([recorder, BlockingPreToolHook(reason="not allowed")])
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        hooks=hooks,
    )

    loop.run("use a blocked tool", run_id="run-pre-block-events")

    assert _tool_call_ids_for(recorder.events, "tool.started") == []
    assert _tool_call_ids_for(recorder.events, "tool.failed") == ["call-blocked"]
    assert _terminal_tool_call_ids(recorder.events) == ["call-blocked"]


def test_post_tool_use_receives_result_after_execution() -> None:
    hook = PostToolRecordingHook()
    tool_call = ToolCall(
        id="call-post",
        name="test_echo",
        arguments={"text": "observed"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(tool_call,)),
            ModelResponse(content="done"),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        hooks=HookManager([hook]),
    )

    loop.run("use a tool", run_id="run-post-hook")

    assert len(hook.contexts) == 1
    assert hook.contexts[0].tool_call.id == "call-post"
    assert hook.contexts[0].tool_result.content == "observed"


def test_pre_tool_use_failure_records_failure_and_defaults_to_allow() -> None:
    tool_call = ToolCall(
        id="call-pre-failure",
        name="test_echo",
        arguments={"text": "still runs"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(tool_call,)),
            ModelResponse(content="done"),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        hooks=HookManager([BrokenPreToolHook()]),
    )

    result = loop.run("use a tool", run_id="run-pre-failure")

    assert result.messages[2].content == "still runs"
    assert ("pre_tool_use", "RuntimeError: pre broke") in result.hook_failures


def test_loop_stops_at_max_turns_when_model_keeps_requesting_tools() -> None:
    llm = ScriptedLlm(
        [
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-1", name="test_echo", arguments={"text": "1"}),
                ),
            ),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-2", name="test_echo", arguments={"text": "2"}),
                ),
            ),
            ModelResponse(content="I stopped after observing 2."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        policy=LoopPolicy(max_turns=2),
    )

    result = loop.run("loop please", run_id="run-max")

    assert result.stop_reason == StopReason.MAX_TURNS
    assert result.final_answer == "I stopped after observing 2."
    assert "<finalization_context>" in llm.system_prompts[-1]
    assert [message.role for message in result.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert llm.calls[-1][1] == ()


def test_max_turn_finalization_never_returns_blank_when_model_asks_for_more_tools() -> None:
    """A stubborn model should not leave the user with an empty final answer."""

    llm = ScriptedLlm(
        [
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-1", name="test_echo", arguments={"text": "1"}),
                ),
            ),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-2", name="test_echo", arguments={"text": "2"}),
                ),
            ),
            ModelResponse(content=""),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        policy=LoopPolicy(max_turns=1),
    )

    result = loop.run("loop please", run_id="run-max-blank")

    assert result.stop_reason == StopReason.MAX_TURNS
    assert result.final_answer
    assert "Tool turn limit reached" in result.final_answer
    assert llm.calls[-1][1] == ()


def test_loop_stops_at_tool_call_budget() -> None:
    llm = ScriptedLlm(
        [
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-1", name="test_echo", arguments={"text": "1"}),
                ),
            ),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-2", name="test_echo", arguments={"text": "2"}),
                    ToolCall(id="call-3", name="test_echo", arguments={"text": "3"}),
                ),
            ),
            ModelResponse(content="I stopped at the tool budget."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        policy=LoopPolicy(max_turns=10, max_tool_calls=2),
    )

    result = loop.run("search broadly", run_id="run-tool-budget")

    assert result.stop_reason == StopReason.MAX_TOOL_CALLS
    assert result.final_answer == "I stopped at the tool budget."
    assert llm.calls[-1][1] == ()
    tool_call_ids = [
        message.tool_call_id for message in result.messages if message.role == "tool"
    ]
    assert tool_call_ids == ["call-1"]


def test_policy_stop_does_not_start_pending_tool_calls() -> None:
    recorder = EventRecorder()
    llm = ScriptedLlm(
        [
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-1", name="test_echo", arguments={"text": "1"}),
                ),
            ),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-2", name="test_echo", arguments={"text": "2"}),
                    ToolCall(id="call-3", name="test_echo", arguments={"text": "3"}),
                ),
            ),
            ModelResponse(content="I stopped at the tool budget."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        hooks=HookManager([recorder]),
        policy=LoopPolicy(max_turns=10, max_tool_calls=2),
    )

    result = loop.run("search broadly", run_id="run-tool-budget-events")

    assert result.stop_reason == StopReason.MAX_TOOL_CALLS
    assert _tool_call_ids_for(recorder.events, "tool.started") == ["call-1"]
    assert _terminal_tool_call_ids(recorder.events) == ["call-1"]
    assert "tool_policy.stopped" in recorder.event_types


def test_loop_stops_at_repeated_tool_call_budget() -> None:
    repeated_call = ToolCall(
        id="call-1",
        name="test_echo",
        arguments={"text": "same"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(repeated_call,)),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        id="call-2",
                        name="test_echo",
                        arguments={"text": "same"},
                    ),
                ),
            ),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        id="call-3",
                        name="test_echo",
                        arguments={"text": "same"},
                    ),
                ),
            ),
            ModelResponse(content="I stopped repeating the same call."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        policy=LoopPolicy(max_turns=10, max_repeated_tool_calls=2),
    )

    result = loop.run("repeat please", run_id="run-repeated-tool")

    assert result.stop_reason == StopReason.REPEATED_TOOL_CALL
    assert result.final_answer == "I stopped repeating the same call."
    assert llm.calls[-1][1] == ()
    tool_call_ids = [
        message.tool_call_id for message in result.messages if message.role == "tool"
    ]
    assert tool_call_ids == ["call-1", "call-2"]


def test_policy_finalization_retries_when_model_requests_tools_again() -> None:
    """Policy finalization should not fall back just because tools were ignored."""

    repeated_call = ToolCall(
        id="call-1",
        name="test_echo",
        arguments={"text": "same"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(repeated_call,)),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        id="call-2",
                        name="test_echo",
                        arguments={"text": "same"},
                    ),
                ),
            ),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        id="call-3",
                        name="test_echo",
                        arguments={"text": "same"},
                    ),
                ),
            ),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        id="call-final",
                        name="test_echo",
                        arguments={"text": "more"},
                    ),
                ),
            ),
            ModelResponse(content="I can answer from the observations I have."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([EchoFixtureTool()]),
        policy=LoopPolicy(max_turns=10, max_repeated_tool_calls=2),
    )

    result = loop.run("repeat please", run_id="run-finalization-retry")

    assert result.stop_reason == StopReason.REPEATED_TOOL_CALL
    assert result.final_answer == "I can answer from the observations I have."
    assert "<finalization_retry_guard>" in result.messages[-2].content
    assert llm.calls[-1][1] == ()


def test_unknown_tool_returns_observation_error() -> None:
    recorder = EventRecorder()
    llm = ScriptedLlm(
        [
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="missing-1", name="missing_tool", arguments={}),
                ),
            ),
            ModelResponse(content="Tool was unavailable."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor(),
        hooks=HookManager([recorder]),
    )

    result = loop.run("call missing", run_id="run-missing-tool")

    assert result.stop_reason == StopReason.FINAL
    assert result.messages[2].role == "tool"
    assert result.messages[2].content == "Unknown tool: missing_tool"
    assert _tool_call_ids_for(recorder.events, "tool.started") == ["missing-1"]
    assert _tool_call_ids_for(recorder.events, "tool.failed") == ["missing-1"]
    assert _terminal_tool_call_ids(recorder.events) == ["missing-1"]


def test_tool_exception_returns_failed_terminal_event() -> None:
    recorder = EventRecorder()
    llm = ScriptedLlm(
        [
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="explode-1", name="test_explode", arguments={}),
                ),
            ),
            ModelResponse(content="Tool failed."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([ExplodingFixtureTool()]),
        hooks=HookManager([recorder]),
    )

    result = loop.run("call exploding tool", run_id="run-tool-exception")

    assert result.stop_reason == StopReason.FINAL
    assert result.messages[2].role == "tool"
    assert result.messages[2].content == "RuntimeError: boom"
    assert _tool_call_ids_for(recorder.events, "tool.started") == ["explode-1"]
    assert _tool_call_ids_for(recorder.events, "tool.failed") == ["explode-1"]
    assert _terminal_tool_call_ids(recorder.events) == ["explode-1"]


def test_tool_result_public_payload_includes_preview_and_length() -> None:
    result = ToolResult(
        tool_call_id="call-long",
        name="test_echo",
        content="x" * 650,
    )

    public = result.to_public_dict()

    assert public["content_length"] == 650
    assert public["content_preview"] == "x" * 500
    assert public["content"] == "x" * 650
