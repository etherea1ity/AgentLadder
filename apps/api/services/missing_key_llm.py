from __future__ import annotations

from agent_ladder.llm.base import BaseLLMClient, LLMResponse, Message


class MissingKeyLLMClient(BaseLLMClient):
    """Explicit runtime failure used when the real DashScope key is absent."""

    def chat(self, messages: list[Message]) -> LLMResponse:
        raise RuntimeError("DASHSCOPE_API_KEY is missing")
