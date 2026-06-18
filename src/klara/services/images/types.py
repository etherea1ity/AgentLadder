"""Image generation service contracts."""

from __future__ import annotations

from dataclasses import dataclass


class ImageProviderError(RuntimeError):
    """Raised when an image provider request cannot complete."""


@dataclass(frozen=True)
class GeneratedImage:
    """One locally persisted image produced by a provider."""

    # Public URL that the frontend can render through the local assets route.
    public_url: str
    # Repository-relative path used by the local asset route.
    local_path: str
    # Short-lived provider URL, kept only for trace/debug context.
    source_url: str
    # Provider id, such as qwen.
    provider: str
    # Provider model id used for generation.
    model: str
    # Prompt sent to the provider.
    prompt: str
    # Optional negative prompt sent to the provider.
    negative_prompt: str
    # Width reported by the provider when available.
    width: int | None = None
    # Height reported by the provider when available.
    height: int | None = None
    # Provider request id when available.
    request_id: str = ""

