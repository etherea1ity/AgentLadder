"""Model-ref router and fallback client for Klara LLM adapters."""

from __future__ import annotations

from dataclasses import dataclass, field

from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolSpec
from klara.infra.config.models import ModelsConfig
from klara.infra.llm.model_ref import ModelRef
from klara.infra.llm.openai_compatible import (
    LlmProviderError,
    OpenAICompatibleLlmClient,
    OpenAICompatibleSettings,
)


@dataclass
class RoutedLlmClient:
    """Route Klara model refs to provider clients and try configured fallbacks."""

    # Provider and profile config loaded from config/models.toml.
    models: ModelsConfig
    # Shared call settings used by OpenAI-compatible providers.
    settings: OpenAICompatibleSettings = field(default_factory=OpenAICompatibleSettings)
    # Optional dotenv path for local development credentials.
    dotenv_path: str | None = None

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
        model: str,
        thinking_enabled: bool | None = None,
    ) -> ModelResponse:
        """Complete one model turn, trying profile fallbacks when configured.

        Args:
            system_prompt: Harness-assembled system prompt.
            messages: Current Klara transcript.
            tools: Visible tool specs for this model turn.
            model: Requested provider/model reference.
            thinking_enabled: Optional per-run provider thinking switch.

        Returns:
            Normalized model response.
        """

        errors: list[str] = []
        # Try the requested model and any profile fallbacks in stable order.
        for candidate in self._candidate_models(model):
            try:
                return self._client_for_model(candidate).complete(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools,
                    model=candidate,
                    thinking_enabled=thinking_enabled,
                )
            except LlmProviderError as exc:
                errors.append(f"{candidate}: {exc}")
                continue
        raise LlmProviderError("all model candidates failed: " + " | ".join(errors))

    def _candidate_models(self, model: str) -> tuple[str, ...]:
        """Return requested model plus fallbacks when it is a profile primary."""

        candidates = [model]
        # Scan profiles so direct model refs can opt into configured fallback chains.
        for profile in self.models.profiles.values():
            if profile.primary == model:
                candidates.extend(item for item in profile.fallbacks if item not in candidates)
                break
        return tuple(candidates)

    def _client_for_model(self, model: str) -> OpenAICompatibleLlmClient:
        """Return a concrete provider client for one model ref."""

        model_ref = ModelRef.parse(model)
        provider = self.models.providers.get(model_ref.provider)
        if provider is None:
            raise LlmProviderError(f"unknown provider: {model_ref.provider}")
        if provider.api != "openai-completions":
            raise LlmProviderError(f"unsupported provider api: {provider.api}")
        return OpenAICompatibleLlmClient(
            provider_id=model_ref.provider,
            provider=provider,
            settings=self.settings,
            dotenv_path=self.dotenv_path,
        )
