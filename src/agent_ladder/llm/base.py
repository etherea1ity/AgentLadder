from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


Message = dict[str, str]


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class LLMStreamChunk:
    delta: str = ""
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    done: bool = False


class BaseLLMClient(ABC):
    """Minimal interface every v0.1 LLM provider must implement."""

    @abstractmethod
    def chat(self, messages: list[Message]) -> LLMResponse:
        """Return one assistant response for a list of chat messages."""
        raise NotImplementedError

    def stream_chat(self, messages: list[Message]) -> Iterator[LLMStreamChunk]:
        """Yield assistant response chunks.

        Providers can override this for native streaming. The default adapts the
        blocking chat call into a single final chunk, which keeps tests simple.
        """
        response = self.chat(messages)
        yield LLMStreamChunk(
            delta=response.content,
            model=response.model,
        )
        yield LLMStreamChunk(
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            done=True,
        )
