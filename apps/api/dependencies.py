from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from agent_ladder.infra.config.loader import load_config
from agent_ladder.llm.providers.dashscope import DashScopeClient
from apps.api.schemas import ModelOption
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.missing_key_llm import MissingKeyLLMClient
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus


def _load_model_options(default_model: str) -> list[ModelOption]:
    path = Path("configs/models.yaml")
    if not path.exists():
        return [ModelOption(id="default", model=default_model, label=default_model)]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = raw.get("models", {})
    options: list[ModelOption] = []
    if isinstance(models, dict):
        for key, value in models.items():
            if not isinstance(value, dict):
                continue
            model = str(value.get("model", "")).strip()
            if not model:
                continue
            options.append(
                ModelOption(
                    id=str(key),
                    model=model,
                    label=str(value.get("label") or model),
                    use_when=_optional_string(value.get("use_when")),
                    enable_thinking=value.get("enable_thinking") if isinstance(value.get("enable_thinking"), bool) else None,
                )
            )
    if all(item.model != default_model for item in options):
        options.insert(0, ModelOption(id="default", model=default_model, label=default_model))
    return options


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_store = JsonlAppStore(os.getenv("AGENT_LADDER_APP_DATA", "data/app"))
_bus = SSEBus()
_config = load_config()
_model_options = _load_model_options(_config.llm.model)


def _create_llm_client(model: str | None = None):
    selected_model = model or _config.llm.model
    if _config.llm.api_key is None:
        return MissingKeyLLMClient()
    option = next((item for item in _model_options if item.model == selected_model), None)
    config = _config.llm.model_copy(
        update={
            "model": selected_model,
            "enable_thinking": option.enable_thinking if option and option.enable_thinking is not None else _config.llm.enable_thinking,
        }
    )
    return DashScopeClient(config)


_llm = _create_llm_client()
_run_service = RunService(
    store=_store,
    bus=_bus,
    llm_client=_llm,
    trace_path=_config.tracing.path,
    llm_client_factory=_create_llm_client,
    allowed_models={item.model for item in _model_options},
    default_model=_config.llm.model,
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
    return _config.llm.model

