"""TOML config loader for Klara infrastructure."""

from __future__ import annotations

import tomllib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from klara.infra.config.images import ImageModel, ImageProviderConfig, ImagesConfig
from klara.infra.config.models import ModelProfile, ModelsConfig, ProviderConfig, ProviderModel
from klara.infra.config.runtime import CapabilityProfile, RuntimeConfig
from klara.core.policies import LoopPolicy
from klara.context.policy import ContextPolicy


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
        max_repeated_final_blocks=_int_config(
            raw_loop,
            "max_repeated_final_blocks",
            env=env,
            env_name="KLARA_LOOP_MAX_REPEATED_FINAL_BLOCKS",
            default=default_policy.max_repeated_final_blocks,
        ),
    )
    raw_runtime = data.get("runtime", {})
    raw_context = raw_runtime.get("context", {})
    default_context = ContextPolicy()
    context_policy = ContextPolicy(
        max_input_tokens=_int_config(
            raw_context,
            "max_input_tokens",
            env=env,
            env_name="KLARA_CONTEXT_MAX_INPUT_TOKENS",
            default=default_context.max_input_tokens,
        ),
        reserved_system_tokens=_int_config(
            raw_context,
            "reserved_system_tokens",
            env=env,
            env_name="KLARA_CONTEXT_RESERVED_SYSTEM_TOKENS",
            default=default_context.reserved_system_tokens,
        ),
        reserved_output_tokens=_int_config(
            raw_context,
            "reserved_output_tokens",
            env=env,
            env_name="KLARA_CONTEXT_RESERVED_OUTPUT_TOKENS",
            default=default_context.reserved_output_tokens,
        ),
        recent_messages=_int_config(
            raw_context,
            "recent_messages",
            env=env,
            env_name="KLARA_CONTEXT_RECENT_MESSAGES",
            default=default_context.recent_messages,
        ),
        minimum_recent_messages=_int_config(
            raw_context,
            "minimum_recent_messages",
            env=env,
            env_name="KLARA_CONTEXT_MINIMUM_RECENT_MESSAGES",
            default=default_context.minimum_recent_messages,
        ),
        summary_max_chars=_int_config(
            raw_context,
            "summary_max_chars",
            env=env,
            env_name="KLARA_CONTEXT_SUMMARY_MAX_CHARS",
            default=default_context.summary_max_chars,
        ),
        tool_result_max_chars=_int_config(
            raw_context,
            "tool_result_max_chars",
            env=env,
            env_name="KLARA_CONTEXT_TOOL_RESULT_MAX_CHARS",
            default=default_context.tool_result_max_chars,
        ),
        chars_per_token=_int_config(
            raw_context,
            "chars_per_token",
            env=env,
            env_name="KLARA_CONTEXT_CHARS_PER_TOKEN",
            default=default_context.chars_per_token,
        ),
    )
    raw_harness = raw_runtime.get("harness", {})
    raw_profiles = raw_runtime.get("capability_profiles", {})
    profiles = tuple(
        CapabilityProfile(
            id=str(profile_id),
            required_model_capabilities=_string_tuple(
                profile_data,
                "required_model_capabilities",
                default=("tools",),
            ),
            visible_tools=_string_tuple(profile_data, "visible_tools"),
            hooks=_string_tuple(profile_data, "hooks", default=("jsonl_trace",)),
            trace_sink=str(profile_data.get("trace_sink", "jsonl")),
        )
        for profile_id, profile_data in raw_profiles.items()
    )
    default_profile = str(raw_harness.get("capability_profile", "agent"))
    runtime = RuntimeConfig(
        loop_policy=policy,
        context_policy=context_policy,
        default_capability_profile=default_profile,
        capability_profiles=profiles or (CapabilityProfile(id="agent"),),
    )
    runtime.profile()
    return runtime


def _string_tuple(
    data: dict[str, Any],
    key: str,
    *,
    default: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Parse one ordered list of unique non-empty strings."""

    value = data.get(key, list(default))
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{key} must be a list of non-empty strings")
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{key} must not contain duplicates")
    return normalized


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
                supports_thinking=bool(
                    item.get(
                        "supports_thinking",
                        item.get("enable_thinking", False),
                    )
                ),
                default_thinking=bool(
                    item.get(
                        "default_thinking",
                        item.get("enable_thinking", False),
                    )
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
