"""TOML config loader for Klara infrastructure."""

from __future__ import annotations

import tomllib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from klara.infra.config.images import ImageModel, ImageProviderConfig, ImagesConfig
from klara.infra.config.models import ModelProfile, ModelsConfig, ProviderConfig, ProviderModel
from klara.infra.config.runtime import RuntimeConfig
from klara.core.policies import LoopPolicy


def load_models_config(config_dir: str | Path = "config") -> ModelsConfig:
    """Load LLM provider and profile config from `models.toml`.

    Args:
        config_dir: Directory containing Klara TOML config files.

    Returns:
        Typed models configuration used by LLM adapters.
    """

    # Keep config loading outside core so the loop never reads files directly.
    raw_data = _load_toml(Path(config_dir) / "models.toml")
    return _models(raw_data)


def load_images_config(config_dir: str | Path = "config") -> ImagesConfig:
    """Load future image-generation provider config from `images.toml`.

    Args:
        config_dir: Directory containing Klara TOML config files.

    Returns:
        Typed image configuration for future media tools.
    """

    # Image config is intentionally separate from chat LLM model selection.
    raw_data = _load_toml(Path(config_dir) / "images.toml")
    return _images(raw_data)


def load_runtime_config(
    config_dir: str | Path = "config",
    *,
    env: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Load runtime execution config from TOML with env overrides.

    Args:
        config_dir: Directory containing Klara TOML config files.
        env: Optional env mapping for tests; process env is used by default.

    Returns:
        Runtime configuration used by app/API assembly.
    """

    raw_data = _load_toml(Path(config_dir) / "runtime.toml")
    return _runtime(raw_data, env=os.environ if env is None else env)


def _load_toml(path: Path) -> dict[str, Any]:
    """Read one TOML file, returning an empty config when it is absent."""

    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def _runtime(data: dict[str, Any], *, env: Mapping[str, str]) -> RuntimeConfig:
    """Parse runtime tables from raw TOML data and environment overrides."""

    raw_loop = data.get("runtime", {}).get("loop", {})
    default_policy = LoopPolicy()
    policy = LoopPolicy(
        max_turns=_int_config(
            raw_loop,
            "max_turns",
            env=env,
            env_name="KLARA_LOOP_MAX_TURNS",
            default=default_policy.max_turns,
        ),
        max_tool_calls=_int_config(
            raw_loop,
            "max_tool_calls",
            env=env,
            env_name="KLARA_LOOP_MAX_TOOL_CALLS",
            default=default_policy.max_tool_calls,
        ),
        max_repeated_tool_calls=_int_config(
            raw_loop,
            "max_repeated_tool_calls",
            env=env,
            env_name="KLARA_LOOP_MAX_REPEATED_TOOL_CALLS",
            default=default_policy.max_repeated_tool_calls,
        ),
    )
    return RuntimeConfig(loop_policy=policy)


def _int_config(
    data: dict[str, Any],
    key: str,
    *,
    env: Mapping[str, str],
    env_name: str,
    default: int,
) -> int:
    """Read one integer config value, with environment taking precedence."""

    env_value = env.get(env_name, "").strip()
    if env_value:
        return int(env_value)
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _models(data: dict[str, Any]) -> ModelsConfig:
    """Parse provider and profile tables from raw TOML data."""

    raw = data.get("models", {})
    providers: dict[str, ProviderConfig] = {}
    for provider_id, provider_data in raw.get("providers", {}).items():
        # Preserve configured model order for future model selection UIs.
        models = tuple(
            ProviderModel(
                id=str(item["id"]),
                label=str(item.get("label", item["id"])),
                supports_tools=bool(item.get("supports_tools", False)),
                supports_json=bool(item.get("supports_json", False)),
                supports_vision=bool(item.get("supports_vision", False)),
                enable_thinking=(
                    bool(item["enable_thinking"])
                    if "enable_thinking" in item
                    else None
                ),
            )
            for item in provider_data.get("models", [])
        )
        providers[str(provider_id)] = ProviderConfig(
            api=str(provider_data["api"]),
            base_url=str(provider_data.get("base_url", "")),
            api_key_env=str(provider_data.get("api_key_env", "")),
            allow_unlisted_models=bool(provider_data.get("allow_unlisted_models", False)),
            models=models,
        )

    profiles = {
        str(profile_id): ModelProfile(
            primary=str(profile_data["primary"]),
            fallbacks=tuple(str(value) for value in profile_data.get("fallbacks", [])),
        )
        for profile_id, profile_data in raw.get("profiles", {}).items()
    }
    return ModelsConfig(providers=providers, profiles=profiles)


def _images(data: dict[str, Any]) -> ImagesConfig:
    """Parse image provider tables from raw TOML data."""

    raw = data.get("images", {})
    providers: dict[str, ImageProviderConfig] = {}
    for provider_id, provider_data in raw.get("providers", {}).items():
        # Preserve configured order so future media UIs remain deterministic.
        models = tuple(
            ImageModel(
                id=str(item["id"]),
                label=str(item.get("label", item["id"])),
                supports_text_to_image=bool(item.get("supports_text_to_image", False)),
                supports_image_editing=bool(item.get("supports_image_editing", False)),
                default_size=str(item.get("default_size", "512*512")),
                verified=bool(item.get("verified", False)),
                verified_note=str(item.get("verified_note", "")),
            )
            for item in provider_data.get("models", [])
        )
        providers[str(provider_id)] = ImageProviderConfig(
            api=str(provider_data["api"]),
            endpoint=str(provider_data["endpoint"]),
            api_key_env=str(provider_data["api_key_env"]),
            models=models,
        )
    return ImagesConfig(providers=providers)
