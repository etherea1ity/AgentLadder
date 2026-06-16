# Klara Configuration

Klara keeps operator configuration in a small number of files:

- `.env` stores local secrets and is ignored by git.
- `.env.example` lists the required and optional environment names.
- `config/models.toml` lists chat LLM providers exposed to the loop.
- `config/images.toml` lists future image-generation providers.

The runtime loop currently uses only chat completions. Image generation
is configured but intentionally not wired into the frontend model picker or loop.

## Required Secrets

```text
DEEPSEEK_API_KEY
DASHSCOPE_API_KEY
```

`DEEPSEEK_API_KEY` serves DeepSeek chat models.

`DASHSCOPE_API_KEY` serves Qwen chat models and the verified future Qwen image
provider in `config/images.toml`.

## Current Chat Models

Chat models live in `config/models.toml`:

```text
deepseek/deepseek-v4-flash
deepseek/deepseek-v4-pro
qwen/qwen3.6-flash
qwen/qwen3.6-plus
```

These are the models that `/api/models` returns to the frontend.

## Future Image Model

Image models live in `config/images.toml`.

`qwen/qwen-image-2.0` has been verified with the local DashScope key, but it is
not part of the chat model picker. When Klara adds image generation, it
should enter as a tool or capability:

```text
LLM loop -> image.generate tool -> Qwen image adapter -> image artifact
```
