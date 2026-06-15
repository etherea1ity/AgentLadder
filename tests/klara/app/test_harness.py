from __future__ import annotations

import json

from klara.app.harness import KlaraHarness, KlaraHarnessConfig
from klara.capabilities.registry import CapabilityRegistry
from klara.capabilities.tools.fake_tool import DebugEchoTool
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolCall, ToolSpec


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
                        name="debug_echo",
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
        registry=CapabilityRegistry([DebugEchoTool()]),
        config=KlaraHarnessConfig(trace_path=trace_path),
    )

    result = harness.run("hello", run_id="harness-run")

    assert result.final_answer == "harness final"
    assert "You are Klara" in llm.system_prompt
    assert "display_name: Local User" in llm.system_prompt
    assert [tool.name for tool in llm.tools] == ["debug_echo"]
    assert llm.messages_seen[1][-1].content == "from harness"

    # Parse trace lines to verify the harness attached a working trace hook.
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert events[0]["type"] == "run.started"
    assert events[-1]["type"] == "run.completed"


def test_harness_defaults_to_chapter1_registry() -> None:
    """Harness should be runnable without manually passing a registry."""

    llm = HarnessLlm()
    harness = KlaraHarness(llm=llm)

    result = harness.run("hello", run_id="default-registry-run")

    assert result.final_answer == "harness final"
    assert [tool.name for tool in llm.tools] == ["debug_echo"]
