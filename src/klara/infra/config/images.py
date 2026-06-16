"""Typed image-generation configuration for future Klara media tools."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ImageModel:
    """One image-capable model exposed by a configured provider."""

    # Provider-local model id, such as qwen-image-2.0.
    id: str
    # Human-readable label for docs and future UI surfaces.
    label: str = ""
    # Whether this model can create an image from a text prompt.
    supports_text_to_image: bool = False
    # Whether this model can edit an input image with instructions.
    supports_image_editing: bool = False
    # Small default size keeps future development probes cheap and fast.
    default_size: str = "512*512"
    # Verified means we have made a successful local provider call.
    verified: bool = False
    # Short operator note for when and how the model was verified.
    verified_note: str = ""


@dataclass(frozen=True)
class ImageProviderConfig:
    """Connection and model-list configuration for one image provider."""

    # Adapter id for future media tools, not for the Chapter 1 chat loop.
    api: str
    # Provider endpoint used by the future image adapter.
    endpoint: str
    # Environment variable name that stores the provider API key.
    api_key_env: str
    # Configured image-capable model entries for this provider.
    models: tuple[ImageModel, ...] = ()


@dataclass(frozen=True)
class ImagesConfig:
    """All configured image providers for future media capabilities."""

    # Provider id to image provider configuration.
    providers: dict[str, ImageProviderConfig] = field(default_factory=dict)
