from __future__ import annotations

import json
import urllib.request

import pytest

from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolCall, ToolSpec
from klara.infra.config.models import ProviderConfig
from klara.infra.config.models import ProviderModel
from klara.infra.llm.model_ref import ModelRef
from klara.infra.llm.openai_compatible import (
    LlmProviderError,
    OpenAICompatibleLlmClient,
    OpenAICompatibleSettings,
    build_chat_completion_payload,
    response_from_completion_data,
)


def test_payload_maps_messages_tools_and_tool_results() -> None:
    """Klara contracts should become OpenAI-compatible chat-completion payloads."""

    payload = build_chat_completion_payload(
        system_prompt="system",
        messages=(
            KlaraMessage(role="user", content="hello"),
            KlaraMessage(
                role="assistant",
                content="",
                tool_calls=(
                    ToolCall(id="call-1", name="lookup", arguments={"text": "x"}),
                ),
            ),
            KlaraMessage(
                role="tool",
                content="x",
                name="lookup",
                tool_call_id="call-1",
            ),
        ),
        tools=(
            ToolSpec(
                name="lookup",
                description="Lookup",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            ),
        ),
        model="deepseek-v4-flash",
        settings=OpenAICompatibleSettings(max_tokens=99, temperature=0.2),
    )

    assert payload["model"] == "deepseek-v4-flash"
    assert payload["messages"][0] == {"role": "system", "content": "system"}
    assert payload["messages"][2]["tool_calls"][0]["function"]["name"] == "lookup"
    assert payload["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "x",
    }
    assert payload["tools"][0]["function"]["name"] == "lookup"
    assert payload["tool_choice"] == "auto"
    assert payload["max_tokens"] == 99


def test_payload_omits_max_tokens_by_default() -> None:
    """Klara should not impose an output cap unless a caller configures one."""

    payload = build_chat_completion_payload(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="qwen-flash",
        settings=OpenAICompatibleSettings(),
    )

    assert "max_tokens" not in payload


def test_payload_can_disable_qwen_thinking_for_tool_calls() -> None:
    """Qwen tool calling should be able to opt out of thinking mode."""

    payload = build_chat_completion_payload(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="qwen3.7-plus",
        settings=OpenAICompatibleSettings(),
        enable_thinking=False,
    )

    assert payload["enable_thinking"] is False


def test_response_from_completion_data_normalizes_tool_calls_and_usage() -> None:
    """Provider responses should return Klara ModelResponse objects."""

    response = response_from_completion_data(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "lookup",
                                    "arguments": "{\"text\":\"x\"}",
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"total_tokens": 12},
        },
        model_ref=ModelRef(provider="deepseek", model="deepseek-v4-flash"),
        raw_preview="{}",
    )

    assert isinstance(response, ModelResponse)
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == {"text": "x"}
    assert response.usage == {"total_tokens": 12}


def test_response_from_completion_data_extracts_provider_reasoning_summary() -> None:
    """Provider reasoning fields should be UI metadata, not assistant content."""

    response = response_from_completion_data(
        {
            "choices": [
                {
                    "message": {
                        "content": "final answer",
                        "reasoning_content": "I checked the request shape before answering.",
                    }
                }
            ],
        },
        model_ref=ModelRef(provider="deepseek", model="deepseek-v4-flash"),
        raw_preview="{}",
    )

    assert response.content == "final answer"
    assert response.reasoning_summary == "I checked the request shape before answering."
    assert response.reasoning_source == "message.reasoning_content"


def test_openai_compatible_client_builds_authenticated_request(monkeypatch) -> None:
    """The provider client should call the configured endpoint without real network."""

    captured: dict[str, object] = {}

    class FakeResponse:
        """Context manager that returns one successful provider response."""

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "live-shaped answer"}}]}
            ).encode("utf-8")

    def fake_urlopen(request: urllib.request.Request, timeout: int) -> FakeResponse:
        """Capture the outgoing request instead of performing network I/O."""

        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[union-attr]
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    client = OpenAICompatibleLlmClient(
        provider_id="deepseek",
        provider=ProviderConfig(
            api="openai-completions",
            base_url="https://api.deepseek.com/v1",
            api_key_env="DEEPSEEK_API_KEY",
            models=(ProviderModel(id="deepseek-v4-flash"),),
        ),
        settings=OpenAICompatibleSettings(timeout_seconds=7, retry_attempts=1),
    )

    response = client.complete(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="deepseek/deepseek-v4-flash",
    )

    assert response.content == "live-shaped answer"
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["timeout"] == 7
    assert captured["payload"]["model"] == "deepseek-v4-flash"
    assert "max_tokens" not in captured["payload"]
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_openai_compatible_client_rejects_missing_key(monkeypatch) -> None:
    """Missing credentials should fail before any provider request."""

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = OpenAICompatibleLlmClient(
        provider_id="deepseek",
        provider=ProviderConfig(
            api="openai-completions",
            base_url="https://api.deepseek.com/v1",
            api_key_env="DEEPSEEK_API_KEY",
            models=(),
            allow_unlisted_models=True,
        ),
    )

    with pytest.raises(LlmProviderError, match="missing API key"):
        client.complete(
            system_prompt="system",
            messages=(KlaraMessage(role="user", content="hello"),),
            tools=(),
            model="deepseek/deepseek-v4-flash",
        )
