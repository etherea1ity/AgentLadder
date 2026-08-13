from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import FrozenInstanceError

from klara.app.harness import KlaraHarness, KlaraHarnessConfig
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.policies import LoopPolicy
from klara.infra.config.models import ModelsConfig, ProviderConfig, ProviderModel
from klara.infra.config.runtime import CapabilityProfile
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
        thinking_enabled: bool | None = None,
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
                        id="activity-1",
                        name="update_activity",
                        arguments={"text": "I will use the echo tool."},
                    ),
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
    assert "Klara is clear, warm, curious, and practical." in llm.system_prompt
    assert "use available runtime tools when they matter" in llm.system_prompt
    assert "call todo_write before substantive actions" in llm.system_prompt
    assert "Answer simple or one-step requests directly" in llm.system_prompt
    assert "<runtime_context>" in llm.system_prompt
    assert "Conversation date:" in llm.system_prompt
    assert "Call current_time only for exact wall-clock time" in llm.system_prompt
    assert "call web_search before answering from memory" in llm.system_prompt
    assert "Keep web_search queries faithful to the user's scope" in llm.system_prompt
    assert "Call web_fetch for source text" in llm.system_prompt
    assert "Search snippets are candidates, not evidence" in llm.system_prompt
    assert "preferred_source" not in llm.system_prompt
    assert "source-limited analysis" not in llm.system_prompt
    assert "Runtime user context" not in llm.system_prompt
    assert [tool.name for tool in llm.tools] == [
        "test_echo",
        "memory_remember",
        "memory_search",
        "memory_update",
        "memory_forget",
        "memory_delete",
        "skills_list",
        "skill_view",
        "update_activity",
    ]
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
        "evidence_submit",
        "image_generate",
        "memory_remember",
        "memory_search",
        "memory_update",
        "memory_forget",
        "memory_delete",
        "skill_view",
        "skills_list",
        "update_activity",
        "web_fetch",
        "web_search",
    }
    assert "Visible tool guidance" not in llm.system_prompt


def test_run_profile_is_stable_immutable_and_secret_free(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "should-never-appear")
    trace_path = tmp_path / "run.jsonl"
    config = KlaraHarnessConfig(
        model="qwen/qwen-flash",
        trace_path=trace_path,
        loop_policy=LoopPolicy(max_turns=7, max_tool_calls=9),
        capability_profile=CapabilityProfile(
            id="test",
            required_model_capabilities=("tools", "json"),
            visible_tools=("test_echo",),
            hooks=("jsonl_trace",),
            trace_sink="jsonl",
        ),
    )
    models = ModelsConfig(
        providers={
            "qwen": ProviderConfig(
                api="openai-completions",
                models=(ProviderModel(id="qwen-flash", supports_tools=True, supports_json=True),),
            )
        }
    )

    first = KlaraHarness(llm=HarnessLlm(), registry=ToolRegistry([EchoFixtureTool()]), config=config, models=models)
    second = KlaraHarness(llm=HarnessLlm(), registry=ToolRegistry([EchoFixtureTool()]), config=config, models=models)

    assert first.run_profile.profile_sha256 == second.run_profile.profile_sha256
    assert first.run_profile.skill_catalog_count >= 1
    assert len(first.run_profile.skill_catalog_sha256) == 64
    public = json.dumps(first.run_profile.to_public_dict(), sort_keys=True)
    assert "should-never-appear" not in public
    assert not any(key.lower() in public.lower() for key in ("api_key", "password", "secret"))
    assert first.run_profile.visible_tools == ("test_echo",)
    try:
        first.run_profile.model = "changed"  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("run profile must stay immutable")


def test_model_capability_mismatch_fails_before_llm_call() -> None:
    llm = HarnessLlm()
    models = ModelsConfig(
        providers={
            "plain": ProviderConfig(
                api="openai-completions",
                models=(ProviderModel(id="no-tools", supports_tools=False),),
            )
        }
    )
    config = KlaraHarnessConfig(
        model="plain/no-tools",
        capability_profile=CapabilityProfile(id="agent", required_model_capabilities=("tools",), hooks=(), trace_sink="none"),
    )

    try:
        KlaraHarness(llm=llm, registry=ToolRegistry([EchoFixtureTool()]), config=config, models=models)
    except ValueError as exc:
        assert str(exc) == "model_capability_mismatch:tools"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("unsupported tool capability must fail before execution")
    assert llm.call_count == 0


def test_capability_profile_rejects_missing_tool_before_run() -> None:
    config = KlaraHarnessConfig(
        capability_profile=CapabilityProfile(
            id="agent",
            visible_tools=("missing_tool",),
            hooks=(),
            trace_sink="none",
        )
    )

    try:
        KlaraHarness(llm=HarnessLlm(), registry=ToolRegistry([EchoFixtureTool()]), config=config)
    except ValueError as exc:
        assert str(exc) == "capability_profile_missing_tools:missing_tool"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("missing configured tool must fail before execution")
