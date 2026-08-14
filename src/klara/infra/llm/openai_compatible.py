"""OpenAI-compatible chat-completions adapter for Klara."""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from klara.core.messages import (
    KlaraMessage,
    LlmRuntimeEvent,
    ModelCallError,
    ModelResponse,
)
from klara.core.tools import ToolCall, ToolSpec
from klara.infra.config.env import get_env_secret
from klara.infra.config.models import ProviderConfig
from klara.infra.llm.model_ref import ModelRef


class LlmProviderError(ModelCallError):
    """Typed provider failure with a trace-safe public taxonomy."""


@dataclass(frozen=True)
class OpenAICompatibleSettings:
    """Per-request settings for OpenAI-compatible chat completions."""

    # Optional provider output cap. None means Klara does not impose a cap.
    max_tokens: int | None = None
    # Sampling temperature for the provider.
    temperature: float = 0.4
    # Network timeout for one blocking provider request.
    # None means Klara does not impose a provider read cap.
    timeout_seconds: int | None = None
    # Retry attempts for transient provider/network failures.
    retry_attempts: int = 3
    # Initial exponential-backoff delay between retryable failures.
    retry_base_delay_seconds: float = 0.5
    # Maximum delay bounds exponential backoff.
    retry_max_delay_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("max_tokens must be positive when provided")
        if self.timeout_seconds is not None and self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive when provided")
        if self.retry_attempts < 1:
            raise ValueError("retry_attempts must be at least 1")
        if self.retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds must be non-negative")
        if self.retry_max_delay_seconds < self.retry_base_delay_seconds:
            raise ValueError("retry_max_delay_seconds must cover the base delay")


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
        thinking_enabled: bool | None = None,
    ) -> ModelResponse:
        """Call the configured provider and return a normalized model response.

        Args:
            system_prompt: Prompt assembled by the Klara harness.
            messages: Current model-visible transcript.
            tools: Tool specs exposed to this model turn.
            model: Provider/model reference, such as deepseek/deepseek-v4-flash.
            thinking_enabled: Optional per-run provider thinking switch.

        Returns:
            Normalized assistant content, tool calls, and usage metadata.
        """

        # Model refs carry provider id plus provider-local model name.
        model_ref = ModelRef.parse(model)
        if model_ref.provider != self.provider_id:
            raise LlmProviderError(
                f"wrong provider client: {self.provider_id} cannot serve {model_ref.provider}",
                code="model_configuration_error",
            )
        if not self.provider.has_model(model_ref.model):
            raise LlmProviderError(
                f"unlisted model for provider {self.provider_id}: {model_ref.model}",
                code="model_configuration_error",
            )

        payload = build_chat_completion_payload(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            model=model_ref.model,
            settings=self.settings,
            include_reasoning_content=model_ref.provider == "deepseek",
            enable_thinking=self._enable_thinking(
                model_ref.model,
                requested=thinking_enabled,
            ),
        )
        all_runtime_events: list[LlmRuntimeEvent] = []
        empty_response_attempts = min(2, self.settings.retry_attempts)
        for response_attempt in range(1, empty_response_attempts + 1):
            request = self._build_http_request(payload)
            raw, runtime_events = _urlopen_with_retries(
                request,
                provider_id=self.provider_id,
                model=model,
                timeout_seconds=self.settings.timeout_seconds,
                attempts=self.settings.retry_attempts,
                retry_base_delay_seconds=self.settings.retry_base_delay_seconds,
                retry_max_delay_seconds=self.settings.retry_max_delay_seconds,
            )
            all_runtime_events.extend(runtime_events)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise LlmProviderError(
                    "provider returned invalid JSON",
                    code="provider_response_invalid",
                    runtime_events=tuple(all_runtime_events),
                ) from exc
            try:
                response = response_from_completion_data(
                    data,
                    model_ref=model_ref,
                    raw_preview=raw[:500],
                )
            except LlmProviderError as exc:
                if (
                    exc.code == "provider_response_empty"
                    and response_attempt < empty_response_attempts
                ):
                    all_runtime_events.append(
                        LlmRuntimeEvent(
                            type="provider.retry_scheduled",
                            payload={
                                "provider": self.provider_id,
                                "model": model,
                                "reason": exc.code,
                                "response_attempt": response_attempt,
                            },
                        )
                    )
                    continue
                exc.runtime_events = tuple(all_runtime_events)
                raise
            return ModelResponse(
                **{
                    **response.__dict__,
                    "model_used": model,
                    "runtime_events": tuple(all_runtime_events),
                }
            )
        raise AssertionError("empty-response retry loop exhausted without result")

    def _enable_thinking(
        self,
        model_id: str,
        *,
        requested: bool | None,
    ) -> bool | None:
        """Return provider-specific thinking mode for this model turn."""

        model = self.provider.model_entry(model_id)
        if model is None or not model.supports_thinking:
            if requested:
                raise LlmProviderError(
                    f"thinking not supported by model: {model_id}",
                    code="model_configuration_error",
                )
            return None
        if requested is None:
            return model.default_thinking
        return requested

    def _build_http_request(self, payload: dict[str, Any]) -> urllib.request.Request:
        """Build one authenticated HTTP request for chat completions."""

        api_key = get_env_secret(self.provider.api_key_env, dotenv_path=self.dotenv_path)
        if not api_key:
            raise LlmProviderError(
                f"missing API key env var: {self.provider.api_key_env}",
                code="provider_credentials_missing",
            )

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
        "stream": False,
    }
    if settings.max_tokens is not None:
        payload["max_tokens"] = settings.max_tokens
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
        native_tool_calls = tuple(
            _parse_tool_call(tool_call, index)
            for index, tool_call in enumerate(raw_tool_calls)
            if isinstance(tool_call, dict)
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmProviderError(
            "provider returned an invalid response shape",
            code="provider_response_invalid",
        ) from exc

    if not isinstance(raw_content, str):
        raise LlmProviderError(
            "provider returned an invalid response shape",
            code="provider_response_invalid",
        )
    dsml_tool_calls: tuple[ToolCall, ...] = ()
    if _contains_dsml_marker(raw_content):
        if native_tool_calls:
            raw_content = ""
        else:
            dsml_tool_calls = _parse_dsml_tool_calls(raw_content)
            raw_content = ""
    tool_calls = native_tool_calls or dsml_tool_calls
    if not raw_content.strip() and not tool_calls:
        raise LlmProviderError(
            "provider returned an empty response",
            code="provider_response_empty",
        )

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    reasoning_source, reasoning_summary = _extract_provider_reasoning(
        data=data,
        choice=choice,
        message=message,
    )
    activity_source, activity_commentary = _extract_public_activity(
        data=data,
        choice=choice,
        message=message,
    )
    return ModelResponse(
        content=raw_content,
        tool_calls=tool_calls,
        usage=usage,
        reasoning_summary=reasoning_summary,
        reasoning_source=reasoning_source,
        activity_commentary=activity_commentary,
        activity_source=activity_source,
    )


def _extract_provider_reasoning(
    *,
    data: dict[str, Any],
    choice: dict[str, Any],
    message: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return one sanitized provider-visible reasoning summary if present."""

    candidates = (
        ("message.reasoning_summary", message.get("reasoning_summary")),
        ("choice.reasoning_summary", choice.get("reasoning_summary")),
        ("data.reasoning_summary", data.get("reasoning_summary")),
    )
    for source, value in candidates:
        if not isinstance(value, str):
            continue
        summary = _sanitize_reasoning_summary(value)
        if summary:
            return source, summary
    return None, None


def _extract_public_activity(
    *,
    data: dict[str, Any],
    choice: dict[str, Any],
    message: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return one sanitized model-authored public activity commentary."""

    candidates = (
        ("message.activity_commentary", message.get("activity_commentary")),
        ("message.public_activity", message.get("public_activity")),
        ("message.commentary", message.get("commentary")),
        ("choice.activity_commentary", choice.get("activity_commentary")),
        ("data.activity_commentary", data.get("activity_commentary")),
        ("data.public_activity", data.get("public_activity")),
        ("data.commentary", data.get("commentary")),
    )
    for source, value in candidates:
        if not isinstance(value, str):
            continue
        commentary = _sanitize_public_activity(value)
        if commentary:
            return source, commentary
    return None, None


def _sanitize_reasoning_summary(value: str) -> str:
    """Return public-safe provider reasoning text for event projection."""

    text = " ".join(value.split())
    if not text:
        return ""
    lowered = text.lower()
    if any(term in lowered for term in ("raw payload", "api key", "secret", "password")):
        return ""
    text = re.sub(r"https?://\S+", "[url]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "sk-[redacted]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    return text


def _sanitize_public_activity(value: str) -> str:
    """Return public-safe activity commentary text."""

    text = _strip_internal_activity_labels(" ".join(value.split()))
    if not text:
        return ""
    lowered = text.lower()
    if any(
        term in lowered
        for term in (
            "chain-of-thought",
            "chain of thought",
            "hidden reasoning",
            "raw reasoning",
            "scratchpad",
            "raw payload",
            "api key",
            "secret",
            "password",
        )
    ):
        return ""
    text = re.sub(r"https?://\S+", "[url]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "sk-[redacted]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    return text


def _strip_internal_activity_labels(text: str) -> str:
    """Remove accidental public echoes of internal activity field labels."""

    pattern = (
        "(?i)\\b(?:update_activity(?:\\.text)?|activity_commentary|public_activity|"
        "assistant_activity(?:_delta)?)\\s*[:\\uff1a]\\s*"
    )
    return re.sub(pattern, "", text).strip()


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


_DSML_TOKEN = r"(?:\|DSML\||｜DSML｜|｜｜DSML｜｜)"
_DSML_MARKER = re.compile(rf"<\s*{_DSML_TOKEN}", re.IGNORECASE)
_DSML_BLOCK = re.compile(
    rf"<\s*{_DSML_TOKEN}(?:tool_calls|function_calls)\s*>"
    rf"(?P<body>.*?)"
    rf"</\s*{_DSML_TOKEN}(?:tool_calls|function_calls)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_DSML_INVOKE = re.compile(
    rf"<\s*{_DSML_TOKEN}invoke\s+name=\"(?P<name>[^\"]+)\"\s*>"
    rf"(?P<body>.*?)"
    rf"</\s*{_DSML_TOKEN}invoke\s*>",
    re.IGNORECASE | re.DOTALL,
)
_DSML_PARAMETER = re.compile(
    rf"<\s*{_DSML_TOKEN}parameter\s+name=\"(?P<name>[^\"]+)\""
    rf"\s+string=\"(?P<string>true|false)\"\s*>"
    rf"(?P<value>.*?)"
    rf"</\s*{_DSML_TOKEN}parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)


def _contains_dsml_marker(content: str) -> bool:
    return bool(_DSML_MARKER.search(content))


def _parse_dsml_tool_calls(content: str) -> tuple[ToolCall, ...]:
    """Normalize DeepSeek V3.2/V4 DSML emitted in the content field."""

    blocks = tuple(_DSML_BLOCK.finditer(content))
    if not blocks or _without_matches(content, blocks).strip():
        raise LlmProviderError(
            "provider returned malformed DSML tool calls",
            code="provider_tool_protocol_invalid",
        )
    calls: list[ToolCall] = []
    for block in blocks:
        body = block.group("body")
        invokes = tuple(_DSML_INVOKE.finditer(body))
        if not invokes or _without_matches(body, invokes).strip():
            raise LlmProviderError(
                "provider returned malformed DSML tool calls",
                code="provider_tool_protocol_invalid",
            )
        for invoke in invokes:
            name = invoke.group("name").strip()
            parameters = tuple(_DSML_PARAMETER.finditer(invoke.group("body")))
            if not name or _without_matches(invoke.group("body"), parameters).strip():
                raise LlmProviderError(
                    "provider returned malformed DSML tool calls",
                    code="provider_tool_protocol_invalid",
                )
            arguments: dict[str, Any] = {}
            for parameter in parameters:
                key = parameter.group("name").strip()
                if not key or key in arguments:
                    raise LlmProviderError(
                        "provider returned malformed DSML tool calls",
                        code="provider_tool_protocol_invalid",
                    )
                raw_value = parameter.group("value").strip()
                if parameter.group("string").lower() == "true":
                    arguments[key] = raw_value
                else:
                    try:
                        arguments[key] = json.loads(raw_value)
                    except json.JSONDecodeError as exc:
                        raise LlmProviderError(
                            "provider returned malformed DSML tool arguments",
                            code="provider_tool_protocol_invalid",
                        ) from exc
            calls.append(
                ToolCall(
                    id=f"dsml-tool-call-{len(calls)}",
                    name=name,
                    arguments=arguments,
                )
            )
    return tuple(calls)


def _without_matches(text: str, matches: tuple[re.Match[str], ...]) -> str:
    """Return text outside a stable set of non-overlapping regex matches."""

    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start()])
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def _urlopen_with_retries(
    request: urllib.request.Request,
    *,
    provider_id: str,
    model: str,
    timeout_seconds: int | None,
    attempts: int,
    retry_base_delay_seconds: float,
    retry_max_delay_seconds: float,
) -> tuple[str, tuple[LlmRuntimeEvent, ...]]:
    """POST to an OpenAI-compatible provider with short transient retries."""

    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last_error: LlmProviderError | None = None
    events: list[LlmRuntimeEvent] = []
    # Retry only around transport/provider overload failures.
    for attempt in range(attempts):
        attempt_number = attempt + 1
        events.append(
            LlmRuntimeEvent(
                type="provider.attempt_started",
                payload={
                    "provider": provider_id,
                    "model": model,
                    "attempt": attempt_number,
                    "max_attempts": attempts,
                    "timeout_seconds": timeout_seconds,
                },
            )
        )
        try:
            if timeout_seconds is None:
                response_context = urllib.request.urlopen(request)
            else:
                response_context = urllib.request.urlopen(
                    request,
                    timeout=timeout_seconds,
                )
            with response_context as response:
                raw = response.read().decode("utf-8")
                events.append(
                    LlmRuntimeEvent(
                        type="provider.attempt_completed",
                        payload={
                            "provider": provider_id,
                            "model": model,
                            "attempt": attempt_number,
                        },
                    )
                )
                return raw, tuple(events)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            code, retryable = _classify_http_error(exc.code, body)
            error = LlmProviderError(
                f"provider HTTP {exc.code} ({code})",
                code=code,
                retryable=retryable,
                status_code=exc.code,
            )
            events.append(
                _provider_attempt_failed_event(
                    provider=provider_id,
                    model=model,
                    attempt=attempt_number,
                    error=error,
                )
            )
            if not retryable:
                error.runtime_events = tuple(events)
                raise error from exc
            last_error = error
        except (
            urllib.error.URLError,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
            TimeoutError,
            ConnectionError,
        ) as exc:
            code = "provider_timeout" if _is_timeout_error(exc) else "provider_transport_error"
            last_error = LlmProviderError(
                f"provider request failed ({code})",
                code=code,
                retryable=True,
            )
            events.append(
                _provider_attempt_failed_event(
                    provider=provider_id,
                    model=model,
                    attempt=attempt_number,
                    error=last_error,
                )
            )
        if attempt + 1 < attempts:
            delay_seconds = min(
                retry_max_delay_seconds,
                retry_base_delay_seconds * (2**attempt),
            )
            events.append(
                LlmRuntimeEvent(
                    type="provider.retry_scheduled",
                    payload={
                        "provider": provider_id,
                        "model": model,
                        "attempt": attempt_number,
                        "next_attempt": attempt_number + 1,
                        "delay_ms": int(delay_seconds * 1000),
                        "reason": last_error.code if last_error else "provider_error",
                    },
                )
            )
            time.sleep(delay_seconds)
    assert last_error is not None
    last_error.runtime_events = tuple(events)
    raise last_error


def _classify_http_error(status_code: int, body: str) -> tuple[str, bool]:
    """Return a stable public error code and whether the same model may retry."""

    lowered = body.lower()
    if status_code in {400, 413, 422} and any(
        marker in lowered
        for marker in (
            "context length",
            "context_length",
            "maximum context",
            "max context",
            "too many tokens",
            "prompt is too long",
        )
    ):
        return "context_length_exceeded", False
    if status_code in {401, 403}:
        return "provider_authentication_failed", False
    if status_code == 408:
        return "provider_timeout", True
    if status_code == 429:
        return "provider_rate_limited", True
    if status_code in {500, 502, 503, 504}:
        return "provider_unavailable", True
    return "provider_request_rejected", False


def _is_timeout_error(exc: BaseException) -> bool:
    """Return whether a transport exception represents a timeout."""

    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, TimeoutError) or "timed out" in str(exc).lower()


def _provider_attempt_failed_event(
    *,
    provider: str,
    model: str,
    attempt: int,
    error: LlmProviderError,
) -> LlmRuntimeEvent:
    """Build a safe failed-attempt event without provider response bodies."""

    return LlmRuntimeEvent(
        type="provider.attempt_failed",
        payload={
            "provider": provider,
            "model": model,
            "attempt": attempt,
            "error_code": error.code,
            "retryable": error.retryable,
            "status_code": error.status_code,
        },
    )
