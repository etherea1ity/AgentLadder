from __future__ import annotations

from klara.infra.config.env import get_env_secret
from klara.infra.config.loader import load_images_config, load_models_config


def test_load_models_config_reads_deepseek_and_qwen() -> None:
    """The default Klara config should expose DeepSeek and Qwen providers."""

    models = load_models_config("config")

    assert list(models.providers) == ["qwen", "deepseek"]
    assert models.providers["deepseek"].base_url == "https://api.deepseek.com/v1"
    assert models.providers["deepseek"].api_key_env == "DEEPSEEK_API_KEY"
    assert models.providers["qwen"].base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_flash = models.providers["qwen"].models[0]
    qwen_plus = models.providers["qwen"].model_entry("qwen3.7-plus")
    assert qwen_flash.id == "qwen-flash"
    assert qwen_flash.label == "Qwen 3.7 Flash"
    assert qwen_flash.supports_tools is True
    assert qwen_flash.supports_vision is False
    assert qwen_flash.enable_thinking is False
    assert qwen_plus is not None
    assert qwen_plus.supports_vision is True
    assert models.profile("agent").primary == "qwen/qwen-flash"


def test_load_images_config_reads_verified_qwen_image_model() -> None:
    """Future media tools should read image config without touching chat config."""

    images = load_images_config("config")
    qwen = images.providers["qwen"]
    model = qwen.models[0]

    assert qwen.api == "dashscope-multimodal-generation"
    assert qwen.api_key_env == "DASHSCOPE_API_KEY"
    assert qwen.endpoint.endswith("/services/aigc/multimodal-generation/generation")
    assert model.id == "qwen-image-2.0-pro"
    assert model.supports_text_to_image is True
    assert model.verified is True


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
