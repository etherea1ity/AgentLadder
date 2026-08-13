from __future__ import annotations

from klara.infra.config.models import ModelProfile, ModelsConfig, ProviderConfig, ProviderModel

from apps.api.dependencies import _default_model, _load_model_options


def test_load_model_options_hides_provider_without_api_key(tmp_path, monkeypatch) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("QWEN_KEY=test-qwen\n", encoding="utf-8")
    monkeypatch.delenv("QWEN_KEY", raising=False)
    monkeypatch.delenv("MISSING_KEY", raising=False)
    models = ModelsConfig(
        providers={
            "qwen": ProviderConfig(
                api="openai-completions",
                api_key_env="QWEN_KEY",
                models=(ProviderModel(id="qwen-flash", label="Qwen Flash"),),
            ),
            "missing": ProviderConfig(
                api="openai-completions",
                api_key_env="MISSING_KEY",
                models=(ProviderModel(id="missing-model", label="Missing"),),
            ),
        }
    )

    options = _load_model_options(models, dotenv_path=dotenv_path)

    assert [option.model for option in options] == ["qwen/qwen-flash"]
    assert options[0].capabilities == []


def test_model_options_publish_capabilities_without_provider_secrets(tmp_path) -> None:
    models = ModelsConfig(
        providers={
            "qwen": ProviderConfig(
                api="openai-completions",
                api_key_env="",
                base_url="https://provider.invalid/v1",
                models=(
                    ProviderModel(
                        id="capable",
                        supports_tools=True,
                        supports_json=True,
                        supports_vision=True,
                        supports_thinking=True,
                    ),
                ),
            )
        }
    )

    option = _load_model_options(models, dotenv_path=tmp_path / ".env")[0]

    assert option.capabilities == ["Tools", "JSON", "Vision", "Thinking"]
    assert "provider.invalid" not in option.model_dump_json()


def test_default_model_falls_back_to_visible_option_when_primary_hidden() -> None:
    models = ModelsConfig(
        profiles={
            "agent": ModelProfile(primary="missing/model")
        }
    )
    options = _load_model_options(
        ModelsConfig(
            providers={
                "qwen": ProviderConfig(
                    api="openai-completions",
                    models=(ProviderModel(id="qwen-flash"),),
                )
            }
        ),
        dotenv_path=None,
    )

    assert _default_model(models, options) == "qwen/qwen-flash"
