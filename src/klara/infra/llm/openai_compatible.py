"""OpenAI-compatible chat-completions adapter for Klara."""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolCall, ToolSpec
from klara.infra.config.env import get_env_secret
from klara.infra.config.models import ProviderConfig
from klara.infra.llm.model_ref import ModelRef


class LlmProviderError(RuntimeError):
    """Raised when a provider request cannot complete or normalize."""


@dataclass(frozen=True)
class OpenAICompatibleSettings:
    """Per-request settings for OpenAI-compatible chat completions."""

    # Maximum output tokens requested from the provider.
    max_tokens: int = 1200
    # Sampling temperature for the provider.
    temperature: float = 0.4
    # Network timeout for one blocking provider request.
    timeout_seconds: int = 60
    # Retry attempts for transient provider/network failures.
    retry_attempts: int = 3
    # Initial exponential-backoff delay between retryable failures.
    retry_base_delay_seconds: float = 0.5


class OpenAICompatibleLlmClient:
    """Call one OpenAI-compatible provider and normalize responses for core.

    This adapter supports DeepSeek and Qwen-style compatible endpoints through
    provider configuration. It owns HTTP, credentials, payload mapping, provider
    response parsing, and retry behavior. Core sees only `ModelResponse`.
    """

    def __init__(
        self,
        *,
        provider_id: str,
        provider: ProviderConfig,
        settings: OpenAICompatibleSettings | None = None,
        dotenv_path: str | None = None,
    ) -> None:
        """Create a provider adapter.

        Args:
            provider_id: Config id used in model refs.
            provider: Provider connection and model-list config.
            settings: Optional provider-call settings.
            dotenv_path: Optional dotenv path for local credentials.
        """

        # Provider id is trace/debug metadata and model-ref validation context.
        self.provider_id = provider_id
        # Provider config holds base URL, API type, API-key env name, and model list.
        self.provider = provider
        # Settings are immutable so tests can assert payload construction.
        self.settings = settings or OpenAICompatibleSettings()
        # Dotenv path is optional and read key-by-key rather than bulk exported.
        self.dotenv_path = dotenv_path

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
        model: str,
    ) -> ModelResponse:
        """Call the configured provider and return a normalized model response.

        Args:
            system_prompt: Prompt assembled by the Klara harness.
            messages: Current model-visible transcript.
            tools: Tool specs exposed to this model turn.
            model: Provider/model reference, such as deepseek/deepseek-v4-flash.

        Returns:
            Normalized assistant content, tool calls, and usage metadata.
        """

        # Model refs carry provider id plus provider-local model name.
        model_ref = ModelRef.parse(model)
        if model_ref.provider != self.provider_id:
            raise LlmProviderError(
                f"wrong provider client: {self.provider_id} cannot serve {model_ref.provider}"
            )
        if not self.provider.has_model(model_ref.model):
            raise LlmProviderError(f"unlisted model for provider {self.provider_id}: {model_ref.model}")

        payload = build_chat_completion_payload(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            model=model_ref.model,
            settings=self.settings,
            include_reasoning_content=model_ref.provider == "deepseek",
            enable_thinking=self._enable_thinking(model_ref.model),
        )
        request = self._build_http_request(payload)
        raw = _urlopen_with_retries(
            request,
            timeout_seconds=self.settings.timeout_seconds,
            attempts=self.settings.retry_attempts,
            retry_base_delay_seconds=self.settings.retry_base_delay_seconds,
        )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LlmProviderError(f"unexpected provider response: {raw[:500]}") from exc
        return response_from_completion_data(data, model_ref=model_ref, raw_preview=raw[:500])

    def _enable_thinking(self, model_id: str) -> bool | None:
        """Return provider-specific thinking mode when configured."""

        model = self.provider.model_entry(model_id)
        return model.enable_thinking if model is not None else None

    def _build_http_request(self, payload: dict[str, Any]) -> urllib.request.Request:
        """Build one authenticated HTTP request for chat completions."""

        api_key = get_env_secret(self.provider.api_key_env, dotenv_path=self.dotenv_path)
        if not api_key:
            raise LlmProviderError(f"missing API key env var: {self.provider.api_key_env}")

        endpoint = f"{self.provider.base_url.rstrip('/')}/chat/completions"
        return urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )


def build_chat_completion_payload(
    *,
    system_prompt: str,
    messages: tuple[KlaraMessage, ...],
    tools: tuple[ToolSpec, ...],
    model: str,
    settings: OpenAICompatibleSettings,
    include_reasoning_content: bool = False,
    enable_thinking: bool | None = None,
) -> dict[str, Any]:
    """Build the provider JSON payload from Klara loop contracts.

    Args:
        system_prompt: Harness-assembled system prompt.
        messages: Model-visible Klara transcript.
        tools: Tool specs visible to the model.
        model: Provider-local model id.
        settings: Output and sampling settings.
        include_reasoning_content: Whether to replay DeepSeek reasoning content.

    Returns:
        OpenAI-compatible chat-completions payload.
    """

    # Provider messages start with the system prompt and then conversation turns.
    provider_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    provider_messages.extend(
        _conversation_messages(messages, include_reasoning_content=include_reasoning_content)
    )

    payload: dict[str, Any] = {
        "model": model,
        "messages": provider_messages,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "stream": False,
    }
    if tools:
        payload["tools"] = [_tool_to_openai_schema(tool) for tool in tools]
        payload["tool_choice"] = "auto"
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking
    return payload


def _conversation_messages(
    messages: tuple[KlaraMessage, ...],
    *,
    include_reasoning_content: bool,
) -> list[dict[str, Any]]:
    """Convert Klara messages into valid OpenAI-compatible conversation items."""

    items: list[dict[str, Any]] = []
    index = 0
    # Walk messages manually so assistant/tool pairs can be kept or dropped together.
    while index < len(messages):
        message = messages[index]
        if message.role == "tool":
            index += 1
            continue
        if message.role == "user":
            items.append({"role": "user", "content": message.content})
            index += 1
            continue

        tool_calls = _wire_tool_calls(message)
        if tool_calls:
            tool_items, next_index = _following_tool_results(messages, index, tool_calls)
            if tool_items:
                items.append(
                    _assistant_wire_message(
                        message,
                        tool_calls=tool_calls,
                        include_reasoning_content=include_reasoning_content,
                    )
                )
                items.extend(tool_items)
                index = next_index
                continue
            if not message.content.strip():
                index += 1
                continue

        items.append(
            _assistant_wire_message(
                message,
                include_reasoning_content=include_reasoning_content,
            )
        )
        index += 1
    return items


def _assistant_wire_message(
    message: KlaraMessage,
    *,
    include_reasoning_content: bool,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one provider assistant message with optional tool calls."""

    item: dict[str, Any] = {"role": "assistant", "content": message.content}
    if tool_calls:
        item["tool_calls"] = tool_calls
    if include_reasoning_content:
        # The loop does not store reasoning content, but the branch is kept for
        # DeepSeek compatibility once public metadata handling exists.
        reasoning_content = getattr(message, "reasoning_content", "")
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            item["reasoning_content"] = reasoning_content
    return item


def _wire_tool_calls(message: KlaraMessage) -> list[dict[str, Any]]:
    """Convert Klara tool calls into OpenAI-compatible assistant metadata."""

    return [
        {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments),
            },
        }
        for call in message.tool_calls
    ]


def _following_tool_results(
    messages: tuple[KlaraMessage, ...],
    assistant_index: int,
    tool_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Collect consecutive tool result messages after assistant tool calls."""

    pending_ids = {str(item["id"]) for item in tool_calls}
    tool_items: list[dict[str, Any]] = []
    index = assistant_index + 1
    # Consume consecutive tool messages that answer the pending assistant calls.
    while index < len(messages) and messages[index].role == "tool":
        tool_call_id = messages[index].tool_call_id
        if tool_call_id in pending_ids:
            tool_items.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": messages[index].content,
                }
            )
            pending_ids.remove(tool_call_id)
        index += 1
    if pending_ids:
        return [], index
    return tool_items, index


def _tool_to_openai_schema(tool: ToolSpec) -> dict[str, Any]:
    """Return one OpenAI-compatible function tool declaration."""

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def response_from_completion_data(
    data: dict[str, Any],
    *,
    model_ref: ModelRef,
    raw_preview: str,
) -> ModelResponse:
    """Normalize a provider completion response into Klara core types."""

    try:
        choice = data["choices"][0]
        message = choice["message"]
        raw_content = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = tuple(
            _parse_tool_call(tool_call, index)
            for index, tool_call in enumerate(raw_tool_calls)
            if isinstance(tool_call, dict)
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmProviderError(f"unexpected provider response: {raw_preview}") from exc

    if not isinstance(raw_content, str):
        raise LlmProviderError(f"unexpected provider response: {raw_preview}")
    if not raw_content.strip() and not tool_calls:
        raise LlmProviderError(f"empty provider response: {raw_preview}")

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    return ModelResponse(content=raw_content, tool_calls=tool_calls, usage=usage)


def _parse_tool_call(raw: dict[str, Any], index: int) -> ToolCall:
    """Normalize one provider tool call object into Klara's ToolCall."""

    function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
    raw_arguments = function.get("arguments", "{}")
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except json.JSONDecodeError:
            arguments = {"_raw": raw_arguments}
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments
    else:
        arguments = {}

    return ToolCall(
        id=str(raw.get("id") or f"tool-call-{index}"),
        name=str(function.get("name") or raw.get("name") or ""),
        arguments=arguments,
    )


def _urlopen_with_retries(
    request: urllib.request.Request,
    *,
    timeout_seconds: int,
    attempts: int,
    retry_base_delay_seconds: float,
) -> str:
    """POST to an OpenAI-compatible provider with short transient retries."""

    last_error: LlmProviderError | None = None
    # Retry only around transport/provider overload failures.
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            error = LlmProviderError(f"provider HTTP {exc.code}: {body[:500]}")
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise error from exc
            last_error = error
        except (
            urllib.error.URLError,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
            TimeoutError,
            ConnectionError,
        ) as exc:
            last_error = LlmProviderError(f"provider request failed: {exc}")
        if attempt + 1 < attempts:
            time.sleep(min(8.0, retry_base_delay_seconds * (2**attempt)))
    assert last_error is not None
    raise last_error
