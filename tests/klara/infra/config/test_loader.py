from __future__ import annotations

from klara.infra.config.env import get_env_secret
from klara.infra.config.loader import load_models_config


def test_load_models_config_reads_deepseek_and_qwen() -> None:
    """The default Klara config should expose DeepSeek and Qwen providers."""

    models = load_models_config("config")

    assert models.providers["deepseek"].base_url == "https://api.deepseek.com/v1"
    assert models.providers["deepseek"].api_key_env == "DEEPSEEK_API_KEY"
    assert models.providers["qwen"].base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert models.profile("agent").primary == "deepseek/deepseek-v4-flash"


def test_get_env_secret_can_read_one_key_from_dotenv_without_exporting_all(tmp_path, monkeypatch) -> None:
    """Dotenv lookup should be key-specific and process env should win."""

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "DEEPSEEK_API_KEY=dotenv-deepseek\nDASHSCOPE_API_KEY='dotenv-qwen'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "process-qwen")

    assert get_env_secret("DEEPSEEK_API_KEY", dotenv_path=dotenv_path) == "dotenv-deepseek"
    assert get_env_secret("DASHSCOPE_API_KEY", dotenv_path=dotenv_path) == "process-qwen"
