from __future__ import annotations

from klara.capabilities.tools.fake_tool import DebugEchoTool
from klara.core.loop import KlaraLoop
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.policies import LoopPolicy, StopReason
from klara.core.tool_executor import ToolExecutor
from klara.core.tools import ToolCall, ToolSpec


class ScriptedLlm:
    """Fake LLM that returns pre-scripted responses in call order."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        """Store scripted responses and model-call observations for assertions."""

        # Responses are consumed so tests can prove turn ordering.
        self.responses = responses
        # Calls keep the model-visible transcript and tool specs per turn.
        self.calls: list[tuple[tuple[KlaraMessage, ...], tuple[ToolSpec, ...]]] = []

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
        self.calls.append((messages, tools))
        if not self.responses:
            raise AssertionError("No scripted LLM response left")
        return self.responses.pop(0)


def test_no_tool_run_returns_final_answer() -> None:
    llm = ScriptedLlm([ModelResponse(content="Hello from Klara.")])
    loop = KlaraLoop(llm=llm, tool_executor=ToolExecutor())

    result = loop.run("hi", run_id="run-no-tool")

    assert result.final_answer == "Hello from Klara."
    assert result.stop_reason == StopReason.FINAL
    assert [message.role for message in result.messages] == ["user", "assistant"]


def test_one_tool_run_feeds_observation_back_to_llm() -> None:
    tool_call = ToolCall(
        id="call-1",
        name="debug_echo",
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
        tool_executor=ToolExecutor([DebugEchoTool()]),
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


def test_loop_stops_at_max_turns_when_model_keeps_requesting_tools() -> None:
    llm = ScriptedLlm(
        [
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-1", name="debug_echo", arguments={"text": "1"}),
                ),
            ),
            ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(id="call-2", name="debug_echo", arguments={"text": "2"}),
                ),
            ),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([DebugEchoTool()]),
        policy=LoopPolicy(max_turns=2),
    )

    result = loop.run("loop please", run_id="run-max")

    assert result.stop_reason == StopReason.MAX_TURNS
    assert result.final_answer == "2"


def test_unknown_tool_returns_observation_error() -> None:
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
    loop = KlaraLoop(llm=llm, tool_executor=ToolExecutor())

    result = loop.run("call missing", run_id="run-missing-tool")

    assert result.stop_reason == StopReason.FINAL
    assert result.messages[2].role == "tool"
    assert result.messages[2].content == "Unknown tool: missing_tool"
