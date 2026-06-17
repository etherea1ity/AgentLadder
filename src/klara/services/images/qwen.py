"""Qwen Image provider adapter."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from klara.infra.config.env import get_env_secret
from klara.infra.config.images import ImageModel, ImageProviderConfig
from klara.services.images.storage import save_image_bytes
from klara.services.images.types import GeneratedImage, ImageProviderError


def generate_qwen_image(
    *,
    provider: ImageProviderConfig,
    model: ImageModel,
    prompt: str,
    negative_prompt: str = "",
    size: str | None = None,
    n: int = 1,
    prompt_extend: bool = True,
    watermark: bool = False,
    seed: int | None = None,
    dotenv_path: str | Path | None = ".env",
    timeout_seconds: int = 180,
) -> tuple[GeneratedImage, ...]:
    """Generate images with Qwen Image and persist provider URLs locally."""

    api_key = get_env_secret(provider.api_key_env, dotenv_path=dotenv_path)
    if not api_key:
        raise ImageProviderError(f"missing API key env var: {provider.api_key_env}")

    payload = _payload(
        model=model,
        prompt=prompt,
        negative_prompt=negative_prompt,
        size=size or model.default_size,
        n=n,
        prompt_extend=prompt_extend,
        watermark=watermark,
        seed=seed,
    )
    raw = _post_json(provider.endpoint, api_key=api_key, payload=payload, timeout_seconds=timeout_seconds)
    data = _json(raw)
    if data.get("code"):
        raise ImageProviderError(f"{data.get('code')}: {data.get('message', '')}".strip())

    urls = _image_urls(data)
    if not urls:
        raise ImageProviderError(f"provider returned no image URL: {raw[:500]}")

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    width = _int_or_none(usage.get("width"))
    height = _int_or_none(usage.get("height"))
    request_id = str(data.get("request_id") or "")
    images: list[GeneratedImage] = []
    for url in urls:
        content = _download(url, timeout_seconds=timeout_seconds)
        local_path, public_url = save_image_bytes(content, extension=_extension_from_url(url))
        images.append(
            GeneratedImage(
                public_url=public_url,
                local_path=local_path,
                source_url=url,
                provider="qwen",
                model=model.id,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                request_id=request_id,
            )
        )
    return tuple(images)


def _payload(
    *,
    model: ImageModel,
    prompt: str,
    negative_prompt: str,
    size: str,
    n: int,
    prompt_extend: bool,
    watermark: bool,
    seed: int | None,
) -> dict[str, Any]:
    """Build the DashScope multimodal-generation payload."""

    parameters: dict[str, Any] = {
        "size": size,
        "n": n,
        "prompt_extend": prompt_extend,
        "watermark": watermark,
    }
    if negative_prompt:
        parameters["negative_prompt"] = negative_prompt
    if seed is not None:
        parameters["seed"] = seed
    return {
        "model": model.id,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        },
        "parameters": parameters,
    }


def _post_json(
    endpoint: str,
    *,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> str:
    """POST JSON to DashScope and return the raw body."""

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ImageProviderError(f"provider HTTP {exc.code}: {body[:500]}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise ImageProviderError(f"provider request failed: {exc}") from exc


def _download(url: str, *, timeout_seconds: int) -> bytes:
    """Download one short-lived provider image URL."""

    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            return response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise ImageProviderError(f"image download failed: {exc}") from exc


def _json(raw: str) -> dict[str, Any]:
    """Parse one JSON object response."""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ImageProviderError(f"unexpected provider response: {raw[:500]}") from exc
    if not isinstance(data, dict):
        raise ImageProviderError(f"unexpected provider response: {raw[:500]}")
    return data


def _image_urls(data: dict[str, Any]) -> tuple[str, ...]:
    """Extract generated image URLs from a DashScope response."""

    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    choices = output.get("choices") if isinstance(output.get("choices"), list) else []
    urls: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("image"), str):
                urls.append(item["image"])
    return tuple(urls)


def _extension_from_url(url: str) -> str:
    """Infer a safe image extension from a URL path."""

    path = url.split("?", 1)[0].lower()
    for extension in (".png", ".jpg", ".jpeg", ".webp"):
        if path.endswith(extension):
            return extension
    return ".png"


def _int_or_none(value: Any) -> int | None:
    """Return an int when the provider value is an integer."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None

