from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json

from klara.context.web_evidence import WebEvidenceGuard
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
class PreferredWebSearchFixtureTool(BaseTool):
    """Test-only web search tool with one preferred source result."""

    spec: ToolSpec = ToolSpec(
        name="web_search",
        description="Return preferred and candidate web results for tests.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": True},
    )
    metadata: ToolMetadata = ToolMetadata(label="Web Search", category="web")

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return a preferred source plus a candidate source."""

        return self.json_success(
            arguments,
            {
                "evidence_status": "candidate_snippets_only",
                "results": [
                    {
                        "title": "Preferred scores",
                        "url": "https://preferred.example/scores",
                        "source_tier": "preferred_source",
                    },
                    {
                        "title": "Candidate scores",
                        "url": "https://candidate.example/scores",
                        "source_tier": "candidate_source",
                    },
                ],
            },
        )


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
        source_tier = (
            "preferred_source" if "preferred.example" in url else "candidate_source"
        )
        return self.json_success(
            arguments,
            {
                "url": url,
                "source_tier": source_tier,
                "text": f"{source_tier} match report text.",
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


def test_no_tool_run_returns_final_answer() -> None:
    llm = ScriptedLlm([ModelResponse(content="Hello from Klara.")])
    loop = KlaraLoop(llm=llm, tool_executor=ToolExecutor())

    result = loop.run("hi", run_id="run-no-tool")

    assert result.final_answer == "Hello from Klara."
    assert result.stop_reason == StopReason.FINAL
    assert [message.role for message in result.messages] == ["user", "assistant"]


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
    assert "<runtime_web_synthesis_guard>" in llm.calls[4][0][-1].content
    assert "2026-06-18" in llm.calls[4][0][-1].content
    search_payload = json.loads(result.messages[2].content)
    assert search_payload["evidence_status"] == "candidate_snippets_only"


def test_mixed_source_quality_requires_final_answer_guard() -> None:
    """The loop should guard final answers built from mixed-quality sources."""

    search_call = ToolCall(
        id="search-1",
        name="web_search",
        arguments={"query": "latest World Cup report"},
    )
    candidate_fetch_call = ToolCall(
        id="fetch-candidate",
        name="web_fetch",
        arguments={"url": "https://candidate.example/scores"},
    )
    preferred_fetch_call = ToolCall(
        id="fetch-preferred",
        name="web_fetch",
        arguments={"url": "https://preferred.example/scores"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(search_call,)),
            ModelResponse(content="", tool_calls=(candidate_fetch_call,)),
            ModelResponse(content="", tool_calls=(preferred_fetch_call,)),
            ModelResponse(content="Candidate-heavy final answer."),
            ModelResponse(content="Preferred-source final answer with URLs."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor([WebSearchFixtureTool(), WebFetchFixtureTool()]),
        policy=LoopPolicy(max_turns=5),
        final_answer_guard=WebEvidenceGuard(),
    )

    result = loop.run("latest World Cup report", run_id="run-source-guard")

    assert result.stop_reason == StopReason.FINAL
    assert result.final_answer == "Preferred-source final answer with URLs."
    assert "Candidate-heavy final answer." not in [
        message.content for message in result.messages
    ]
    assert "<runtime_source_guard>" in llm.calls[4][0][-1].content
    final_call_tools = {
        message.tool_call_id: message.content
        for message in llm.calls[4][0]
        if message.role == "tool"
    }
    assert "candidate_source match report text" not in final_call_tools["fetch-candidate"]
    assert "hidden by runtime_source_guard" in final_call_tools["fetch-candidate"]
    assert "preferred_source match report text" in final_call_tools["fetch-preferred"]


def test_preferred_source_search_result_requires_preferred_fetch_before_final() -> None:
    """The loop should not finalize from candidates when preferred URLs exist."""

    search_call = ToolCall(
        id="search-1",
        name="web_search",
        arguments={"query": "latest World Cup report"},
    )
    candidate_fetch_call = ToolCall(
        id="fetch-candidate",
        name="web_fetch",
        arguments={"url": "https://candidate.example/scores"},
    )
    preferred_fetch_call = ToolCall(
        id="fetch-preferred",
        name="web_fetch",
        arguments={"url": "https://preferred.example/scores"},
    )
    llm = ScriptedLlm(
        [
            ModelResponse(content="", tool_calls=(search_call,)),
            ModelResponse(content="", tool_calls=(candidate_fetch_call,)),
            ModelResponse(content="Candidate-only final answer."),
            ModelResponse(content="", tool_calls=(preferred_fetch_call,)),
            ModelResponse(content="Mixed-source final answer."),
            ModelResponse(content="Preferred-source final answer."),
        ]
    )
    loop = KlaraLoop(
        llm=llm,
        tool_executor=ToolExecutor(
            [PreferredWebSearchFixtureTool(), WebFetchFixtureTool()]
        ),
        policy=LoopPolicy(max_turns=6),
        final_answer_guard=WebEvidenceGuard(),
    )

    result = loop.run("latest World Cup report", run_id="run-preferred-guard")

    assert result.stop_reason == StopReason.FINAL
    assert result.final_answer == "Preferred-source final answer."
    assert "Candidate-only final answer." not in [
        message.content for message in result.messages
    ]
    assert "<runtime_preferred_source_guard>" in llm.calls[3][0][-1].content
    assert "https://preferred.example/scores" in llm.calls[3][0][-1].content
    assert "<runtime_source_guard>" in llm.calls[5][0][-1].content
