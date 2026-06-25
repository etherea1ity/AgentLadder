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
