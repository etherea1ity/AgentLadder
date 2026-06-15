"""TOML config loader for Klara infrastructure."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from klara.infra.config.models import ModelProfile, ModelsConfig, ProviderConfig, ProviderModel


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


def _load_toml(path: Path) -> dict[str, Any]:
    """Read one TOML file, returning an empty config when it is absent."""

    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


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
