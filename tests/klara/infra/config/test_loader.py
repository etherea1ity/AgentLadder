from __future__ import annotations

from klara.infra.config.env import get_env_secret
from klara.infra.config.loader import (
    load_images_config,
    load_models_config,
    load_runtime_config,
)


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
    assert qwen_flash.supports_thinking is True
    assert qwen_flash.default_thinking is False
    assert qwen_plus is not None
    assert qwen_plus.supports_vision is True
    assert qwen_plus.supports_thinking is True
    assert qwen_plus.default_thinking is False
    deepseek_pro = models.providers["deepseek"].model_entry("deepseek-v4-pro")
    assert deepseek_pro is not None
    assert deepseek_pro.label == "DeepSeek V4 Pro"
    assert deepseek_pro.supports_thinking is True
    assert deepseek_pro.default_thinking is True
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


def test_load_runtime_config_reads_loop_policy() -> None:
    """Runtime loop limits should live outside core defaults."""

    runtime = load_runtime_config("config", env={})

    assert runtime.loop_policy.max_turns == 24
    assert runtime.loop_policy.max_tool_calls == 48
    assert runtime.loop_policy.max_repeated_tool_calls == 3


def test_load_runtime_config_env_overrides_toml(tmp_path) -> None:
    """Deployment env should override runtime TOML without editing files."""

    (tmp_path / "runtime.toml").write_text(
        "\n".join(
            [
                "[runtime.loop]",
                "max_turns = 11",
                "max_tool_calls = 22",
                "max_repeated_tool_calls = 2",
            ]
        ),
        encoding="utf-8",
    )

    runtime = load_runtime_config(
        tmp_path,
        env={
            "KLARA_LOOP_MAX_TURNS": "31",
            "KLARA_LOOP_MAX_TOOL_CALLS": "62",
            "KLARA_LOOP_MAX_REPEATED_TOOL_CALLS": "4",
        },
    )

    assert runtime.loop_policy.max_turns == 31
    assert runtime.loop_policy.max_tool_calls == 62
    assert runtime.loop_policy.max_repeated_tool_calls == 4


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
