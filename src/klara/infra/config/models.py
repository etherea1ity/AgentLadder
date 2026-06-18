"""Typed model configuration for Klara LLM providers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderModel:
    """One model entry exposed by a configured provider."""

    # Provider-local model id, such as deepseek-v4-flash.
    id: str
    # Human-readable label for docs and future UI surfaces.
    label: str = ""
    # Whether this model can return structured tool calls.
    supports_tools: bool = False
    # Whether this model can reliably produce JSON-style output.
    supports_json: bool = False
    # Whether this model can accept image inputs in chat messages.
    supports_vision: bool = False
    # Provider-specific thinking switch; Qwen tools need this disabled.
    enable_thinking: bool | None = None


@dataclass(frozen=True)
class ProviderConfig:
    """Connection and model-list configuration for one LLM provider."""

    # API adapter id, currently only openai-completions.
    api: str
    # OpenAI-compatible base URL without the /chat/completions suffix.
    base_url: str = ""
    # Environment variable name that stores the provider API key.
    api_key_env: str = ""
    # Whether users may request provider/model ids not listed in config.
    allow_unlisted_models: bool = False
    # Configured model entries for this provider.
    models: tuple[ProviderModel, ...] = ()

    def has_model(self, model_id: str) -> bool:
        """Return whether this provider explicitly lists a model id.

        Args:
            model_id: Provider-local model id to check.

        Returns:
            True when the model is listed or unlisted models are allowed.
        """

        # Unlisted models are an explicit provider-level escape hatch.
        if self.allow_unlisted_models:
            return True
        return any(model.id == model_id for model in self.models)

    def model_entry(self, model_id: str) -> ProviderModel | None:
        """Return the configured model entry when one is listed."""

        return next((model for model in self.models if model.id == model_id), None)


@dataclass(frozen=True)
class ModelProfile:
    """Primary model plus ordered fallback model references."""

    # First model ref the harness should try for this profile.
    primary: str
    # Fallback refs are tried in order when the primary provider fails.
    fallbacks: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelsConfig:
    """All configured LLM providers and named routing profiles."""

    # Provider id to provider configuration.
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    # Profile id to primary/fallback model refs.
    profiles: dict[str, ModelProfile] = field(default_factory=dict)

    def profile(self, profile_id: str = "agent") -> ModelProfile:
        """Return a configured model profile by id.

        Args:
            profile_id: Profile name from models.toml.

        Returns:
            The configured profile.

        Raises:
            KeyError: If the profile is missing.
        """

        return self.profiles[profile_id]
