# Klara Configuration

Klara keeps operator configuration in a small number of files:

- `.env` stores local secrets and is ignored by git.
- `.env.example` lists the required and optional environment names.
- `config/models.toml` lists chat LLM providers exposed to the loop.
- `config/images.toml` lists image-generation providers used by media tools.

The runtime loop uses chat completions for decisions and calls image generation
through the `image_generate` tool when the user asks for an image.

## Required Secrets

```text
DEEPSEEK_API_KEY
DASHSCOPE_API_KEY
```

`DEEPSEEK_API_KEY` serves DeepSeek chat models.

`DASHSCOPE_API_KEY` serves Qwen chat models and the Qwen image provider in
`config/images.toml`.

## Current Chat Models

Chat models live in `config/models.toml`:

```text
deepseek/deepseek-v4-flash
deepseek/deepseek-v4-pro
qwen/qwen3.7-plus
qwen/qwen3.7-max
```

These are the models that `/api/models` returns to the frontend.

The default `agent` profile is `qwen/qwen3.7-plus` so Klara can use one default
model for text, tool calling, and image understanding.

## Image Tool Model

Image models live in `config/images.toml`.

`qwen-image-2.0-pro` is the default text-to-image model for the
`image_generate` tool, with `qwen-image-2.0` kept as a configured fallback.
Generated provider URLs are downloaded into `data/assets/images/...` and then
shown through the local assets route:

```text
LLM loop -> image_generate tool -> Qwen image adapter -> local Markdown image link
```
