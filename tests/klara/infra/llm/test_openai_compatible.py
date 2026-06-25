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


def test_payload_can_set_provider_thinking_mode() -> None:
    """Provider thinking mode should be an explicit per-request payload option."""

    payload = build_chat_completion_payload(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="qwen3.7-plus",
        settings=OpenAICompatibleSettings(),
        enable_thinking=True,
    )

    assert payload["enable_thinking"] is True


def test_openai_compatible_client_uses_model_default_thinking(monkeypatch) -> None:
    """Model config defaults should control thinking when the run has no override."""

    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: int | None = None,
    ) -> FakeResponse:
        captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[union-attr]
        return FakeResponse()

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = OpenAICompatibleLlmClient(
        provider_id="qwen",
        provider=ProviderConfig(
            api="openai-completions",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key_env="DASHSCOPE_API_KEY",
            models=(
                ProviderModel(
                    id="qwen-flash",
                    supports_thinking=True,
                    default_thinking=False,
                ),
            ),
        ),
        settings=OpenAICompatibleSettings(retry_attempts=1),
    )

    client.complete(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="qwen/qwen-flash",
    )

    assert captured["payload"]["enable_thinking"] is False


def test_openai_compatible_client_accepts_run_thinking_override(monkeypatch) -> None:
    """Run-level thinking should override the model default for supported models."""

    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: int | None = None,
    ) -> FakeResponse:
        captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[union-attr]
        return FakeResponse()

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = OpenAICompatibleLlmClient(
        provider_id="qwen",
        provider=ProviderConfig(
            api="openai-completions",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key_env="DASHSCOPE_API_KEY",
            models=(
                ProviderModel(
                    id="qwen-flash",
                    supports_thinking=True,
                    default_thinking=False,
                ),
            ),
        ),
        settings=OpenAICompatibleSettings(retry_attempts=1),
    )

    client.complete(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="qwen/qwen-flash",
        thinking_enabled=True,
    )

    assert captured["payload"]["enable_thinking"] is True


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


def test_response_from_completion_data_extracts_message_thinking() -> None:
    """Qwen-style thinking fields should become UI-only reasoning metadata."""

    response = response_from_completion_data(
        {
            "choices": [
                {
                    "message": {
                        "content": "final answer",
                        "thinking": "The provider returned a public thinking summary.",
                    }
                }
            ],
        },
        model_ref=ModelRef(provider="qwen", model="qwen3.7-flash"),
        raw_preview="{}",
    )

    assert response.content == "final answer"
    assert response.reasoning_summary == "The provider returned a public thinking summary."
    assert response.reasoning_source == "message.thinking"


def test_response_from_completion_data_extracts_data_reasoning() -> None:
    """Top-level reasoning fields are accepted when message-level fields are absent."""

    response = response_from_completion_data(
        {
            "choices": [{"message": {"content": "final answer"}}],
            "reasoning": "The provider returned top-level reasoning metadata.",
        },
        model_ref=ModelRef(provider="qwen", model="qwen3.7-flash"),
        raw_preview="{}",
    )

    assert response.content == "final answer"
    assert response.reasoning_summary == "The provider returned top-level reasoning metadata."
    assert response.reasoning_source == "data.reasoning"


def test_response_from_completion_data_extracts_public_activity_commentary() -> None:
    """Structured public activity fields should be UI metadata."""

    response = response_from_completion_data(
        {
            "choices": [
                {
                    "message": {
                        "content": "final answer",
                        "activity_commentary": (
                            "update_activity.text: I will handle this as a "
                            "tool-backed task."
                        ),
                    }
                }
            ],
        },
        model_ref=ModelRef(provider="qwen", model="qwen3.7-flash"),
        raw_preview="{}",
    )

    assert response.content == "final answer"
    assert response.activity_commentary == "I will handle this as a tool-backed task."
    assert response.activity_source == "message.activity_commentary"


def test_response_from_completion_data_keeps_tool_call_content_for_loop_activity() -> None:
    """Loop owns the content+tool_calls split so providers stay normalized."""

    response = response_from_completion_data(
        {
            "choices": [
                {
                    "message": {
                        "content": "I will check with a tool first.",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "lookup",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ],
        },
        model_ref=ModelRef(provider="qwen", model="qwen3.7-flash"),
        raw_preview="{}",
    )

    assert response.content == "I will check with a tool first."
    assert response.tool_calls


def test_response_from_completion_data_sanitizes_provider_reasoning() -> None:
    """Reasoning metadata should not expose full URLs or secret-shaped values."""

    response = response_from_completion_data(
        {
            "choices": [
                {
                    "message": {
                        "content": "final answer",
                        "reasoning_content": (
                            "I checked https://example.com/private and token=abc123 "
                            "with sk-abcdefghijklmnopqrstuvwxyz."
                        ),
                    }
                }
            ],
        },
        model_ref=ModelRef(provider="deepseek", model="deepseek-v4-flash"),
        raw_preview="{}",
    )

    assert response.reasoning_summary is not None
    assert "https://example.com/private" not in response.reasoning_summary
    assert "token=abc123" not in response.reasoning_summary
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in response.reasoning_summary


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


def test_openai_compatible_client_does_not_cap_provider_reads_by_default(monkeypatch) -> None:
    """Long thinking calls should not inherit a short adapter read timeout."""

    captured: dict[str, object | None] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: int | None = None,
    ) -> FakeResponse:
        captured["timeout"] = timeout
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
        settings=OpenAICompatibleSettings(retry_attempts=1),
    )

    response = client.complete(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="deepseek/deepseek-v4-flash",
    )

    assert response.content == "ok"
    assert captured["timeout"] is None


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
