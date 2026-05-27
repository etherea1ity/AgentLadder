from __future__ import annotations

from collections.abc import Iterator

from openai import OpenAI

from agent_ladder.infra.config.loader import LLMConfig
from agent_ladder.llm.base import BaseLLMClient, LLMResponse, LLMStreamChunk, Message


class DashScopeClient(BaseLLMClient):
    """DashScope client using its OpenAI-compatible chat completions API."""

    def __init__(self, config: LLMConfig) -> None:
        if config.provider != "dashscope":
            raise ValueError(f"DashScopeClient requires provider='dashscope', got {config.provider!r}")
        if config.api_key is None:
            raise ValueError("DASHSCOPE_API_KEY is required. Add it to your local .env file.")

        self.config = config
        self.client = OpenAI(
            api_key=config.api_key.get_secret_value(),
            base_url=config.base_url,
        )

    def chat(self, messages: list[Message]) -> LLMResponse:
        completion = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            stream=False,
            extra_body={"enable_thinking": self.config.enable_thinking},
        )

        choice = completion.choices[0]
        content = choice.message.content or ""
        usage = completion.usage

        return LLMResponse(
            content=content,
            model=completion.model or self.config.model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )

    def stream_chat(self, messages: list[Message]) -> Iterator[LLMStreamChunk]:
        completion = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            stream=True,
            stream_options={"include_usage": True},
            extra_body={"enable_thinking": self.config.enable_thinking},
        )

        final_model = self.config.model
        prompt_tokens = None
        completion_tokens = None

        for chunk in completion:
            if getattr(chunk, "model", None):
                final_model = chunk.model
            usage = getattr(chunk, "usage", None)
            if usage:
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # Deliberately ignore reasoning_content/raw thinking fields. The UI
            # only receives safe activity summaries and answer text.
            content = getattr(delta, "content", None)
            if content:
                yield LLMStreamChunk(delta=content, model=final_model)

        yield LLMStreamChunk(
            model=final_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            done=True,
        )
