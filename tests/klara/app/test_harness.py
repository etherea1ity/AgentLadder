from __future__ import annotations

import json
from dataclasses import dataclass

from klara.app.harness import KlaraHarness, KlaraHarnessConfig
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import JsonObject, ToolCall, ToolMetadata, ToolResult, ToolSpec
from klara.tools.base import BaseTool
from klara.tools.registry import ToolRegistry


@dataclass(frozen=True)
class EchoFixtureTool(BaseTool):
    """Test-only echo fixture for harness wiring."""

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


class HarnessLlm:
    """Fake LLM that proves the harness assembled prompt, tools, and messages."""

    def __init__(self) -> None:
        """Capture harness inputs across model calls."""

        # System prompt proves persona and user context assembly.
        self.system_prompt = ""
        # Tools prove the registry was converted into model-visible specs.
        self.tools: tuple[ToolSpec, ...] = ()
        # Messages prove tool observations are fed back on the second call.
        self.messages_seen: list[tuple[KlaraMessage, ...]] = []
        # Call count controls the fake two-turn tool flow.
        self.call_count = 0

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
        model: str,
    ) -> ModelResponse:
        """Request a tool on the first call and final-answer on the second."""

        self.system_prompt = system_prompt
        self.tools = tools
        self.messages_seen.append(messages)
        self.call_count += 1
        if self.call_count == 1:
            return ModelResponse(
                content="",
                tool_calls=(
                    ToolCall(
                        id="echo-1",
                        name="test_echo",
                        arguments={"text": "from harness"},
                    ),
                ),
            )
        return ModelResponse(content="harness final")


def test_harness_assembles_persona_tools_user_context_and_trace(tmp_path) -> None:
    llm = HarnessLlm()
    trace_path = tmp_path / "run.jsonl"
    harness = KlaraHarness(
        llm=llm,
        registry=ToolRegistry([EchoFixtureTool()]),
        config=KlaraHarnessConfig(trace_path=trace_path),
    )

    result = harness.run("hello", run_id="harness-run")

    assert result.final_answer == "harness final"
    assert "You are Klara" in llm.system_prompt
    assert "must call the image-generation tool" in llm.system_prompt
    assert "Never invent local image URLs" in llm.system_prompt
    assert "<runtime_context>" in llm.system_prompt
    assert "Conversation date:" in llm.system_prompt
    assert "Call current_time only for exact wall-clock time" in llm.system_prompt
    assert "call web_search before answering from memory" in llm.system_prompt
    assert "Runtime user context" not in llm.system_prompt
    assert [tool.name for tool in llm.tools] == ["test_echo"]
    assert llm.messages_seen[1][-1].content == "from harness"

    # Parse trace lines to verify the harness attached a working trace hook.
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert events[0]["type"] == "run.started"
    assert events[-1]["type"] == "run.completed"


def test_harness_defaults_to_default_registry() -> None:
    """Harness should be runnable without manually passing a registry."""

    llm = HarnessLlm()
    llm.call_count = 1
    harness = KlaraHarness(llm=llm)

    result = harness.run("hello", run_id="default-registry-run")

    assert result.final_answer == "harness final"
    assert {tool.name for tool in llm.tools} == {
        "current_time",
        "image_generate",
        "web_fetch",
        "web_search",
    }
    assert "Visible tool guidance" not in llm.system_prompt
