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

    def fake_complete(self, *, system_prompt, messages, tools, model, thinking_enabled=None):
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
                    fallbacks=("qwen/qwen3.7-plus",),
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

    assert response.content == "ok from qwen/qwen3.7-plus"
    assert response.model_used == "qwen/qwen3.7-plus"
    assert calls == ["deepseek/deepseek-v4-flash", "qwen/qwen3.7-plus"]
    assert [event.type for event in response.runtime_events] == [
        "model_route.candidate_started",
        "model_route.candidate_failed",
        "model_route.fallback_started",
        "model_route.candidate_started",
        "model_route.candidate_completed",
    ]


def test_routed_client_returns_prompt_too_long_to_loop_without_fallback(monkeypatch) -> None:
    """The loop must compact before the router considers another model."""

    calls: list[str] = []

    def fake_complete(self, *, system_prompt, messages, tools, model, thinking_enabled=None):
        calls.append(model)
        raise LlmProviderError(
            "prompt rejected",
            code="context_length_exceeded",
            status_code=400,
        )

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
                    fallbacks=("qwen/qwen3.7-plus",),
                )
            },
        )
    )

    with pytest.raises(LlmProviderError) as caught:
        client.complete(
            system_prompt="system",
            messages=(KlaraMessage(role="user", content="hello"),),
            tools=(),
            model="deepseek/deepseek-v4-flash",
        )

    assert caught.value.code == "context_length_exceeded"
    assert calls == ["deepseek/deepseek-v4-flash"]
    assert "model_route.fallback_started" not in {
        event.type for event in caught.value.runtime_events
    }


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


def test_routed_client_skips_sibling_models_after_provider_auth_failure(monkeypatch) -> None:
    calls: list[str] = []

    qwen_attempts = 0

    def fake_complete(self, *, system_prompt, messages, tools, model, thinking_enabled=None):
        nonlocal qwen_attempts
        calls.append(model)
        if model.startswith("qwen/"):
            qwen_attempts += 1
            if qwen_attempts == 1:
                raise LlmProviderError(
                    "invalid provider credential",
                    code="provider_authentication_failed",
                    status_code=401,
                )
            return ModelResponse(content="qwen credential recovered")
        return ModelResponse(content="recovered")

    monkeypatch.setenv("QWEN_TEST_KEY", "credential-one")
    monkeypatch.setattr(
        "klara.infra.llm.openai_compatible.OpenAICompatibleLlmClient.complete",
        fake_complete,
    )
    client = RoutedLlmClient(
        models=ModelsConfig(
            providers={
                "qwen": ProviderConfig(
                    api="openai-completions",
                    api_key_env="QWEN_TEST_KEY",
                    allow_unlisted_models=True,
                ),
                "deepseek": ProviderConfig(
                    api="openai-completions", allow_unlisted_models=True
                ),
            },
            profiles={
                "agent": ModelProfile(
                    primary="qwen/primary",
                    fallbacks=("qwen/sibling", "deepseek/recovery"),
                )
            },
        )
    )

    response = client.complete(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="qwen/primary",
    )

    assert response.content == "recovered"
    assert calls == ["qwen/primary", "deepseek/recovery"]
    skipped = [
        event for event in response.runtime_events
        if event.type == "model_route.candidate_skipped"
    ]
    assert len(skipped) == 1
    assert skipped[0].payload["candidate_model"] == "qwen/sibling"
    assert "credential-one" not in repr(response.runtime_events)

    monkeypatch.setenv("QWEN_TEST_KEY", "credential-two")
    recovered = client.complete(
        system_prompt="system",
        messages=(KlaraMessage(role="user", content="hello"),),
        tools=(),
        model="qwen/primary",
    )
    assert recovered.content == "qwen credential recovered"
    assert calls[-1] == "qwen/primary"
