from __future__ import annotations

import pytest

from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolSpec
from klara.infra.config.models import ModelProfile, ModelsConfig, ProviderConfig
from klara.infra.llm.openai_compatible import LlmProviderError
from klara.infra.llm.routed_client import RoutedLlmClient


def test_routed_client_tries_profile_fallback(monkeypatch) -> None:
    """Router should use profile fallbacks when the primary provider fails."""

    calls: list[str] = []

    def fake_complete(self, *, system_prompt, messages, tools, model):
        calls.append(model)
        if model == "deepseek/deepseek-v4-flash":
            raise LlmProviderError("primary down")
        return ModelResponse(content=f"ok from {model}")

    monkeypatch.setattr(
        "klara.infra.llm.openai_compatible.OpenAICompatibleLlmClient.complete",
        fake_complete,
    )

    client = RoutedLlmClient(
        models=ModelsConfig(
            providers={
                "deepseek": ProviderConfig(api="openai-completions", allow_unlisted_models=True),
                "qwen": ProviderConfig(api="openai-completions", allow_unlisted_models=True),
            },
            profiles={
                "agent": ModelProfile(
                    primary="deepseek/deepseek-v4-flash",
                    fallbacks=("qwen/qwen3.6-flash",),
                )
            },
        )
    )

    response = client.complete(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="deepseek/deepseek-v4-flash",
    )

    assert response.content == "ok from qwen/qwen3.6-flash"
    assert calls == ["deepseek/deepseek-v4-flash", "qwen/qwen3.6-flash"]


def test_routed_client_rejects_unknown_provider() -> None:
    """Unknown provider ids should fail before adapter construction."""

    client = RoutedLlmClient(models=ModelsConfig())

    with pytest.raises(LlmProviderError, match="unknown provider"):
        client.complete(
            system_prompt="system",
            messages=(KlaraMessage(role="user", content="hello"),),
            tools=(),
            model="missing/model",
        )
