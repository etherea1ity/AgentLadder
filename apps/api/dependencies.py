from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from apps.api.schemas import ModelOption
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus
from klara.app.user_context import UserContext
from klara.infra.config.env import get_env_secret
from klara.infra.config.loader import load_models_config, load_runtime_config
from klara.infra.config.models import ModelsConfig
from klara.infra.llm.routed_client import RoutedLlmClient


def _load_model_options(
    models: ModelsConfig,
    *,
    dotenv_path: str | Path | None = ".env",
) -> list[ModelOption]:
    """Build UI model options from Klara's TOML provider registry."""

    options: list[ModelOption] = []
    for provider_id, provider in models.providers.items():
        if provider.api_key_env and not get_env_secret(provider.api_key_env, dotenv_path=dotenv_path):
            continue
        for item in provider.models:
            model_ref = f"{provider_id}/{item.id}"
            options.append(
                ModelOption(
                    id=model_ref,
                    model=model_ref,
                    label=item.label or model_ref,
                    use_when=_model_use_when(provider_id, item.supports_vision),
                    supports_thinking=item.supports_thinking,
                    default_thinking=item.default_thinking,
                )
            )
    return options


def _default_model(models: ModelsConfig, options: list[ModelOption]) -> str:
    """Return the configured primary model when available, otherwise a visible model."""

    profile = models.profile("agent")
    visible_models = {item.model for item in options}
    if profile.primary in visible_models:
        return profile.primary
    if options:
        return options[0].model
    return profile.primary


def _model_use_when(provider_id: str, supports_vision: bool) -> str:
    """Return a compact UI hint for one configured model."""

    if supports_vision:
        return f"{provider_id} provider, vision-capable"
    return f"{provider_id} provider"


def _local_user_context() -> UserContext:
    """Build the local app user context, including prompt timezone."""

    timezone = os.getenv("KLARA_TIMEZONE", "local").strip() or "local"
    return replace(UserContext.local_default(), timezone=timezone)


_store = JsonlAppStore(os.getenv("KLARA_APP_DATA", "data/app"))
_bus = SSEBus()
_models = load_models_config(Path("config"))
_runtime = load_runtime_config(Path("config"))
_model_options = _load_model_options(_models)
_default_model_ref = _default_model(_models, _model_options)
_llm = RoutedLlmClient(models=_models, dotenv_path=".env")
_run_service = RunService(
    store=_store,
    bus=_bus,
    llm_client=_llm,
    trace_path=os.getenv("KLARA_TRACE_PATH", "data/traces/runs.jsonl"),
    allowed_models={item.model for item in _model_options},
    thinking_support={item.model: item.supports_thinking for item in _model_options},
    default_thinking={item.model: item.default_thinking for item in _model_options},
    default_model=_default_model_ref,
    loop_policy=_runtime.loop_policy,
    user_context=_local_user_context(),
)


def get_store() -> JsonlAppStore:
    return _store


def get_bus() -> SSEBus:
    return _bus


def get_run_service() -> RunService:
    return _run_service


def get_model_options() -> list[ModelOption]:
    return _model_options


def get_default_model() -> str:
    return _default_model_ref
