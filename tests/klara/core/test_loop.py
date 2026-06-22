from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json

from klara.context.web_evidence import WebEvidenceGuard
from klara.core.hooks import (
    HookDecision,
    HookManager,
    PostToolUseContext,
    PreToolUseContext,
)
from klara.core.loop import KlaraLoop
from klara.core.messages import KlaraMessage, ModelResponse
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
class WebSearchFixtureTool(BaseTool):
    """Test-only web search tool that returns candidate snippets."""

    spec: ToolSpec = ToolSpec(
        name="web_search",
        description="Return candidate web search results for tests.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": True},
    )
    metadata: ToolMetadata = ToolMetadata(label="Web Search", category="web")

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return a candidate-only web observation."""

        return self.json_success(
            arguments,
            {
                "evidence_status": "candidate_snippets_only",
                "results": [
                    {
                        "title": "World Cup scores",
                        "url": "https://example.com/scores",
                        "snippet": "candidate snippet",
                    }
                ],
            },
        )


@dataclass(frozen=True)
class FailingWebSearchFixtureTool(BaseTool):
    """Test-only web search tool that fails before returning candidates."""

    spec: ToolSpec = ToolSpec(
        name="web_search",
        description="Fail web search for tests.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": True},
    )
    metadata: ToolMetadata = ToolMetadata(label="Web Search", category="web")

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return a provider-style failure observation."""

        return self.failure(arguments, "URL host must resolve to a public IP address")


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


@dataclass(frozen=True)
class WebFetchFixtureTool(BaseTool):
    """Test-only web fetch tool that returns source text."""

    spec: ToolSpec = ToolSpec(
        name="web_fetch",
        description="Fetch source text for tests.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": True},
    )
    metadata: ToolMetadata = ToolMetadata(label="Web Fetch", category="web")

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return fetched source text."""

        url = str(arguments.get("url", ""))
        return self.json_success(
            arguments,
            {
                "url": url,
                "text": "Fetched match report text.",
            },
        )


@dataclass(frozen=True)
class DatedWebFetchFixtureTool(BaseTool):
    """Test-only fetch tool that returns a current-or-past event date."""

    spec: ToolSpec = ToolSpec(
        name="web_fetch",
        description="Fetch dated source text for tests.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": True},
    )
    metadata: ToolMetadata = ToolMetadata(label="Web Fetch", category="web")

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return fetched text with an event start date before the run date."""

        url = str(arguments.get("url", "https://example.com/scores"))
        return self.json_success(
            arguments,
            {
                "url": url,
                "final_url": url,
                "status": 200,
                "title": "Dated event page",
                "text": (
                    "The tournament runs from June 11, 2026 to July 19, 2026. "
                    "18 Jun 2026: Team A 2-1 Team B."
                ),
            },
        )


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


def test_current_fact_request_requires_initial_web_search_before_final() -> None:
    """The loop should not ask permission instead of searching current facts."""

    search_call = ToolCall(
        id="search-1",
        name="web_search",
        arguments={"query": "World Cup matches results so far"},
    )
    fetch_call = ToolCall(
        id="fetch-1",
        name="web_fetch",
        arguments={"url": "https://example.com/scores"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="I can search now. Start?"),
            ModelResponse(content="", tool_calls=(search_call,)),
            ModelResponse(content="", tool_calls=(fetch_call,)),
            ModelResponse(content="Fetched report without source caveat."),
            ModelResponse(content="Final answer from fetched source."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([WebSearchFixtureTool(), WebFetchFixtureTool()]),
        policy=LoopPolicy(max_turns=6),
        final_answer_guard=WebEvidenceGuard(current_date=date(2026, 6, 18)),
    )

    result = loop.run(
        "\u7ed9\u6211\u4e00\u4e2a\u603b\u7ed3\uff0c"
        "\u4e16\u754c\u676f\u5230\u76ee\u524d\u7684\u6bcf\u4e00\u573a"
        "\u6bd4\u8d5b\u3001\u6bd4\u8d5b\u603b\u7ed3\u548c\u7403\u5458\u8868\u73b0",
        run_id="run-initial-web-search-guard",
    )

    assert result.stop_reason == StopReason.FINAL
    assert result.final_answer == "Final answer from fetched source."
    assert "I can search now. Start?" not in [
        message.content for message in result.messages
    ]
    initial_guard = llm.calls[1][0][-1].content
    assert "<runtime_web_search_required_guard>" in initial_guard
    assert "Do not ask the user whether to search" in initial_guard
    assert [message.name for message in result.messages if message.role == "tool"] == [
        "web_search",
        "web_fetch",
    ]


def test_web_search_candidate_observation_requires_fetch_before_final() -> None:
    """The loop should not let search snippets become the final evidence."""

    search_call = ToolCall(
        id="search-1",
        name="web_search",
        arguments={"query": "latest World Cup report"},
    )
    fetch_call = ToolCall(
        id="fetch-1",
        name="web_fetch",
        arguments={"url": "https://example.com/scores"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(search_call,)),
            ModelResponse(content="The snippets say the tournament has not started."),
            ModelResponse(content="", tool_calls=(fetch_call,)),
            ModelResponse(content="Fetched report with stale schedule copy."),
            ModelResponse(content="Fetched match report text."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([WebSearchFixtureTool(), WebFetchFixtureTool()]),
        policy=LoopPolicy(max_turns=5),
        final_answer_guard=WebEvidenceGuard(
            current_date=date(2026, 6, 18),
            timezone_name="Asia/Shanghai",
        ),
    )

    result = loop.run("latest World Cup report", run_id="run-web-guard")

    assert result.stop_reason == StopReason.FINAL
    assert result.final_answer == "Fetched match report text."
    assert "tournament has not started" not in [
        message.content for message in result.messages
    ]
    assert [message.role for message in result.messages] == [
        "user",
        "assistant",
        "tool",
        "user",
        "assistant",
        "tool",
        "user",
        "assistant",
    ]
    assert "<runtime_tool_guard>" in llm.calls[2][0][-1].content
    synthesis_guard = llm.calls[4][0][-1].content
    assert "<runtime_web_synthesis_guard>" in synthesis_guard
    assert "2026-06-18" in synthesis_guard
    assert "Do not invent quotes, numeric ratings" in synthesis_guard
    assert "separate the complete factual list" in synthesis_guard
    search_payload = json.loads(result.messages[2].content)
    assert search_payload["evidence_status"] == "candidate_snippets_only"


def test_failed_web_search_blocks_memory_based_current_fact_answer() -> None:
    """Failed searches should not let the model answer current facts from memory."""

    search_call = ToolCall(
        id="search-1",
        name="web_search",
        arguments={"query": "World Cup results so far"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(search_call,)),
            ModelResponse(content="The tournament has not started."),
            ModelResponse(content="I could not retrieve current web evidence."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([FailingWebSearchFixtureTool()]),
        policy=LoopPolicy(max_turns=5),
        final_answer_guard=WebEvidenceGuard(current_date=date(2026, 6, 18)),
    )

    result = loop.run("latest World Cup results", run_id="run-failed-search")

    assert result.stop_reason == StopReason.FINAL
    assert result.final_answer == "I could not retrieve current web evidence."
    assert "The tournament has not started." not in [
        message.content for message in result.messages
    ]
    guard = llm.calls[2][0][-1].content
    assert "<runtime_web_search_failure_guard>" in guard
    assert "Do not answer current facts from memory" in guard


def test_repeated_failed_search_guard_returns_safe_fallback() -> None:
    """Repeated ignored search-failure guards should end with a safe answer."""

    search_call = ToolCall(
        id="search-1",
        name="web_search",
        arguments={"query": "World Cup results so far"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(search_call,)),
            ModelResponse(content="The tournament has not started."),
            ModelResponse(content="The tournament has not started."),
            ModelResponse(content="The tournament has not started."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([FailingWebSearchFixtureTool()]),
        policy=LoopPolicy(max_turns=8),
        final_answer_guard=WebEvidenceGuard(current_date=date(2026, 6, 18)),
    )

    result = loop.run(
        "\u6700\u65b0\u4e16\u754c\u676f\u8d5b\u679c",
        run_id="run-failed-search-fallback",
    )

    assert result.stop_reason == StopReason.FINAL
    assert result.final_answer.startswith(
        "\u6211\u8fd9\u8f6e\u5df2\u7ecf\u5c1d\u8bd5\u68c0\u7d22"
        "\u5f53\u524d\u7f51\u9875\u8bc1\u636e"
    )
    assert result.messages[-1].role == "assistant"
    assert result.messages[-1].content == result.final_answer


def test_web_search_fetch_guard_does_not_repeat_until_max_turns() -> None:
    """A model that ignores one fetch guard should finalize without spinning."""

    search_call = ToolCall(
        id="search-1",
        name="web_search",
        arguments={"query": "latest World Cup report"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(search_call,)),
            ModelResponse(content="I can answer from snippets."),
            ModelResponse(content="Source evidence is insufficient."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([WebSearchFixtureTool(), WebFetchFixtureTool()]),
        policy=LoopPolicy(max_turns=24),
        final_answer_guard=WebEvidenceGuard(current_date=date(2026, 6, 18)),
    )

    result = loop.run("latest World Cup report", run_id="run-one-fetch-guard")

    assert result.stop_reason == StopReason.FINAL
    assert result.final_answer == "Source evidence is insufficient."
    assert len(llm.calls) == 3
    assert "<runtime_tool_guard>" in llm.calls[2][0][-1].content


def test_temporal_guard_rejects_not_started_draft_after_dated_web_evidence() -> None:
    """The loop should not return a not-started draft that conflicts with dates."""

    fetch_call = ToolCall(
        id="fetch-1",
        name="web_fetch",
        arguments={"url": "https://example.com/scores"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(fetch_call,)),
            ModelResponse(content="The tournament has not started."),
            ModelResponse(
                content=(
                    "\u76ee\u524d\u4e16\u754c\u676f\u5c1a\u672a\u5f00"
                    "\u59cb\uff0c\u6ca1\u6709\u5b9e\u9645\u8fdb\u884c"
                    "\u8fc7\u7684\u6bd4\u8d5b\u3002"
                )
            ),
            ModelResponse(
                content=(
                    "\u5df2\u6709\u6bd4\u8d5b\u65e5\u671f\uff1b\u7ed3"
                    "\u679c\u53ef\u5217\uff0c\u8bc4\u8bba\u8bc1\u636e"
                    "\u4e0d\u8db3\u3002"
                )
            ),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([DatedWebFetchFixtureTool()]),
        policy=LoopPolicy(max_turns=6),
        final_answer_guard=WebEvidenceGuard(current_date=date(2026, 6, 18)),
    )

    result = loop.run("latest World Cup report", run_id="run-temporal-guard")

    assert result.stop_reason == StopReason.FINAL
    assert result.final_answer == (
        "\u5df2\u6709\u6bd4\u8d5b\u65e5\u671f\uff1b\u7ed3"
        "\u679c\u53ef\u5217\uff0c\u8bc4\u8bba\u8bc1\u636e"
        "\u4e0d\u8db3\u3002"
    )
    assert "<runtime_web_synthesis_guard>" in llm.calls[2][0][-1].content
    temporal_guard = llm.calls[3][0][-1].content
    assert "<runtime_temporal_consistency_guard>" in temporal_guard
    assert "Do not repeat a blanket 'not started' claim" in temporal_guard
