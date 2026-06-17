from __future__ import annotations

import json

from klara.capabilities.tools.image_generate import ImageGenerateTool
from klara.core.tools import ToolSideEffect
from klara.infra.config.images import ImageModel, ImageProviderConfig
from klara.services.images import GeneratedImage


def test_image_generate_tool_declares_serial_network_metadata() -> None:
    """Image generation should be a serial network tool in the first version."""

    tool = ImageGenerateTool()

    assert tool.spec.name == "image_generate"
    assert tool.spec.input_schema["required"] == ["prompt"]
    assert "Never invent /api/assets/local" in tool.spec.description
    assert tool.metadata.category == "media"
    assert tool.metadata.side_effect == ToolSideEffect.NETWORK
    assert tool.metadata.parallel_safe is False


def test_image_generate_tool_returns_markdown_image_observation() -> None:
    """Generated images should return Markdown links for the final answer."""

    def generator(
        *,
        provider: ImageProviderConfig,
        model: ImageModel,
        prompt: str,
        negative_prompt: str,
        size: str | None,
        n: int,
        prompt_extend: bool,
        watermark: bool,
        seed: int | None,
        timeout_seconds: int,
    ) -> tuple[GeneratedImage, ...]:
        assert provider.api == "dashscope-multimodal-generation"
        assert model.id == "qwen-image-2.0-pro"
        assert prompt == "draw Klara"
        assert size == "1024*1024"
        assert n == 1
        return (
            GeneratedImage(
                public_url="/api/assets/local?path=data/assets/images/test.png",
                local_path="data/assets/images/test.png",
                source_url="https://example.com/tmp.png",
                provider="qwen",
                model=model.id,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=1024,
                height=1024,
            ),
        )

    tool = ImageGenerateTool(generator=generator)

    result = tool.execute({"prompt": "draw Klara", "size": "1024*1024"})

    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["kind"] == "image_generation"
    assert payload["model"] == "qwen-image-2.0-pro"
    assert payload["images"][0]["markdown"] == (
        "![Generated image](/api/assets/local?path=data/assets/images/test.png)"
    )
    assert "final answer" in payload["final_answer_instruction"].lower()
    assert "do not split the url" in payload["final_answer_instruction"].lower()
