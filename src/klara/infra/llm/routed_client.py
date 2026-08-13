"""Model-ref router and fallback client for Klara LLM adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib

from klara.core.messages import KlaraMessage, LlmRuntimeEvent, ModelResponse
from klara.core.tools import ToolSpec
from klara.infra.config.models import ModelsConfig
from klara.infra.llm.model_ref import ModelRef
from klara.infra.config.env import get_env_secret
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
    _authentication_failures: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )

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

        events: list[LlmRuntimeEvent] = []
        # Try the requested model and any profile fallbacks in stable order.
        candidates = self._candidate_models(model)
        for index, candidate in enumerate(candidates):
            provider_id = ModelRef.parse(candidate).provider
            if self._provider_authentication_is_open(provider_id):
                events.append(
                    LlmRuntimeEvent(
                        type="model_route.candidate_skipped",
                        payload={
                            "requested_model": model,
                            "candidate_model": candidate,
                            "candidate_index": index,
                            "reason": "provider_authentication_circuit_open",
                        },
                    )
                )
                if index + 1 < len(candidates):
                    events.append(
                        LlmRuntimeEvent(
                            type="model_route.fallback_started",
                            payload={
                                "requested_model": model,
                                "failed_model": candidate,
                                "fallback_model": candidates[index + 1],
                                "reason": "provider_authentication_circuit_open",
                            },
                        )
                    )
                continue
            events.append(
                LlmRuntimeEvent(
                    type="model_route.candidate_started",
                    payload={
                        "requested_model": model,
                        "candidate_model": candidate,
                        "candidate_index": index,
                        "candidate_count": len(candidates),
                    },
                )
            )
            try:
                response = self._client_for_model(candidate).complete(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools,
                    model=candidate,
                    thinking_enabled=thinking_enabled,
                )
            except LlmProviderError as exc:
                if exc.code == "provider_authentication_failed":
                    self._open_provider_authentication_circuit(provider_id)
                events.extend(exc.runtime_events)
                events.append(
                    LlmRuntimeEvent(
                        type="model_route.candidate_failed",
                        payload={
                            "requested_model": model,
                            "candidate_model": candidate,
                            "candidate_index": index,
                            "error_code": exc.code,
                            "retryable": exc.retryable,
                            "status_code": exc.status_code,
                        },
                    )
                )
                if exc.code in {"context_length_exceeded", "model_configuration_error"}:
                    exc.runtime_events = tuple(events)
                    raise
                if index + 1 < len(candidates):
                    events.append(
                        LlmRuntimeEvent(
                            type="model_route.fallback_started",
                            payload={
                                "requested_model": model,
                                "failed_model": candidate,
                                "fallback_model": candidates[index + 1],
                                "reason": exc.code,
                            },
                        )
                    )
                continue
            events.extend(response.runtime_events)
            events.append(
                LlmRuntimeEvent(
                    type="model_route.candidate_completed",
                    payload={
                        "requested_model": model,
                        "model_used": candidate,
                        "fallback_used": candidate != model,
                        "candidate_index": index,
                    },
                )
            )
            return ModelResponse(
                **{
                    **response.__dict__,
                    "model_used": candidate,
                    "runtime_events": tuple(events),
                }
            )
        raise LlmProviderError(
            "all configured model candidates failed",
            code="all_model_candidates_failed",
            runtime_events=tuple(events),
        )

    def _credential_fingerprint(self, provider_id: str) -> str:
        provider = self.models.providers.get(provider_id)
        if provider is None or not provider.api_key_env:
            return ""
        value = get_env_secret(provider.api_key_env, dotenv_path=self.dotenv_path)
        return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else "missing"

    def _provider_authentication_is_open(self, provider_id: str) -> bool:
        failed_fingerprint = self._authentication_failures.get(provider_id)
        if failed_fingerprint is None:
            return False
        current = self._credential_fingerprint(provider_id)
        if current != failed_fingerprint:
            self._authentication_failures.pop(provider_id, None)
            return False
        return True

    def _open_provider_authentication_circuit(self, provider_id: str) -> None:
        self._authentication_failures[provider_id] = self._credential_fingerprint(provider_id)

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
            raise LlmProviderError(
                f"unknown provider: {model_ref.provider}",
                code="model_configuration_error",
            )
        if provider.api != "openai-completions":
            raise LlmProviderError(
                f"unsupported provider api: {provider.api}",
                code="model_configuration_error",
            )
        return OpenAICompatibleLlmClient(
            provider_id=model_ref.provider,
            provider=provider,
            settings=self.settings,
            dotenv_path=self.dotenv_path,
        )
