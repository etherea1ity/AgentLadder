"""Model-visible image generation capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from klara.tools.base import BaseTool, ToolInputError
from klara.tools.builtin.image_generate.schema import (
    IMAGE_GENERATE_METADATA,
    IMAGE_GENERATE_SPEC,
)
from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec
from klara.infra.config.images import ImageModel, ImageProviderConfig
from klara.infra.config.loader import load_images_config
from klara.services.images import GeneratedImage, ImageProviderError, generate_qwen_image


ImageGenerator = Callable[..., tuple[GeneratedImage, ...]]


@dataclass(frozen=True)
class ImageGenerateTool(BaseTool):
    """Generate images and return local Markdown links for the final answer."""

    spec: ToolSpec = IMAGE_GENERATE_SPEC
    metadata: ToolMetadata = IMAGE_GENERATE_METADATA
    generator: ImageGenerator = generate_qwen_image

    def run(self, arguments: JsonObject) -> ToolResult:
        """Generate images from a text prompt.

        Args:
            arguments: JSON-like arguments with prompt and optional image parameters.

        Returns:
            JSON observation containing local image URLs and Markdown snippets.
        """

        prompt = self.optional_string(arguments, "prompt")
        if not prompt:
            raise ToolInputError("prompt must not be empty")
        negative_prompt = self.optional_string(arguments, "negative_prompt")
        size = self.optional_string(arguments, "size")
        n = _optional_int(arguments, "n", default=1)
        if n < 1 or n > 2:
            raise ToolInputError("n must be between 1 and 2")
        prompt_extend = _optional_bool(arguments, "prompt_extend", default=True)
        watermark = _optional_bool(arguments, "watermark", default=False)
        seed = _optional_int_or_none(arguments, "seed")

        provider, model = _default_qwen_image_model()
        try:
            images = self.generator(
                provider=provider,
                model=model,
                prompt=prompt,
                negative_prompt=negative_prompt,
                size=size or None,
                n=n,
                prompt_extend=prompt_extend,
                watermark=watermark,
                seed=seed,
                timeout_seconds=int(self.metadata.timeout_seconds),
            )
        except ImageProviderError as exc:
            return self.failure(arguments, str(exc))

        return self.json_success(
            arguments,
            {
                "kind": "image_generation",
                "provider": "qwen",
                "model": model.id,
                "image_count": len(images),
                "images": [
                    {
                        "public_url": image.public_url,
                        "local_path": image.local_path,
                        "width": image.width,
                        "height": image.height,
                        "markdown": f"![Generated image]({image.public_url})",
                    }
                    for image in images
                ],
                "final_answer_instruction": (
                    "In the final answer, embed each generated image using each "
                    "markdown field exactly as one unbroken Markdown image tag. "
                    "Do not split the URL, do not print a bare URL, and then add "
                    "a brief natural-language note."
                ),
            },
        )


def _default_qwen_image_model() -> tuple[ImageProviderConfig, ImageModel]:
    """Return the first configured Qwen text-to-image model."""

    images = load_images_config("config")
    provider = images.providers.get("qwen")
    if provider is None:
        raise ToolInputError("qwen image provider is not configured")
    for model in provider.models:
        if model.supports_text_to_image:
            return provider, model
    raise ToolInputError("no qwen text-to-image model is configured")


def _optional_bool(arguments: JsonObject, key: str, *, default: bool) -> bool:
    """Read an optional boolean argument."""

    value = arguments.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ToolInputError(f"{key} must be a boolean")
    return value


def _optional_int(arguments: JsonObject, key: str, *, default: int) -> int:
    """Read an optional integer argument."""

    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{key} must be an integer")
    return value


def _optional_int_or_none(arguments: JsonObject, key: str) -> int | None:
    """Read an optional integer argument that may be absent."""

    if key not in arguments:
        return None
    value = _optional_int(arguments, key, default=0)
    if value < 0 or value > 2147483647:
        raise ToolInputError(f"{key} must be between 0 and 2147483647")
    return value
