from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr


DEFAULT_CONFIG_PATH = Path("configs/default.yaml")
DEFAULT_ENV_PATH = Path(".env")


class LLMConfig(BaseModel):
    provider: str
    base_url: str
    model: str
    temperature: float
    stream: bool
    enable_thinking: bool
    api_key: SecretStr | None = None


class TracingConfig(BaseModel):
    enabled: bool
    path: str


class AppConfig(BaseModel):
    llm: LLMConfig
    tracing: TracingConfig


def load_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    env_path: str | Path = DEFAULT_ENV_PATH,
) -> AppConfig:
    """Load AgentLadder config from YAML plus local environment variables.

    configs/default.yaml owns runtime settings such as provider, model, base_url,
    and trace path. The local .env file owns secrets such as DASHSCOPE_API_KEY.
    """
    root = _find_project_root()

    env_file = _resolve_path(root, env_path)
    if env_file.exists():
        load_dotenv(env_file)

    config_file = _resolve_path(root, config_path)
    raw_config = _read_yaml(config_file)

    llm_config = dict(raw_config.get("llm", {}))
    tracing_config = dict(raw_config.get("tracing", {}))

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if api_key:
        llm_config["api_key"] = api_key

    # Local override for quick model switching without editing YAML.
    # Example: AGENT_LADDER_MODEL=qwen3.6-plus
    model_override = os.getenv("AGENT_LADDER_MODEL")
    if model_override:
        llm_config["model"] = model_override

    enable_thinking_override = os.getenv("AGENT_LADDER_ENABLE_THINKING")
    if enable_thinking_override is not None:
        llm_config["enable_thinking"] = enable_thinking_override.strip().lower() in {"1", "true", "yes", "on"}

    return AppConfig(
        llm=LLMConfig(**llm_config),
        tracing=TracingConfig(**tracing_config),
    )


def _find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if (path / "configs" / "default.yaml").exists():
            return path
    return current


def _resolve_path(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a YAML object: {path}")
    return loaded
