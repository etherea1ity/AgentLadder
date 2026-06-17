"""Schema and runtime metadata for the image-generation tool."""

from __future__ import annotations

from klara.core.tools import ToolMetadata, ToolSideEffect, ToolSpec


IMAGE_GENERATE_SPEC = ToolSpec(
    name="image_generate",
    description=(
        "Generate one or two images from a visual prompt. Use this when the "
        "user asks to draw, create, render, make an illustration, poster, "
        "mockup, or other image. The observation returns Markdown image links "
        "that can be embedded in the final answer beside normal text. Never "
        "invent /api/assets/local URLs or data/assets/images paths yourself; "
        "call this tool and copy the returned Markdown image links exactly."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed visual prompt describing subject, style, composition, lighting, and any text to render.",
            },
            "negative_prompt": {
                "type": "string",
                "description": "Optional things to avoid in the generated image.",
            },
            "size": {
                "type": "string",
                "description": "Optional output size like 1024*1024, 1536*864, or 864*1536.",
            },
            "n": {
                "type": "integer",
                "minimum": 1,
                "maximum": 2,
                "description": "Optional image count. Use 1 unless the user asks for alternatives.",
            },
            "prompt_extend": {
                "type": "boolean",
                "description": "Whether Qwen may enrich the prompt. Default true.",
            },
            "watermark": {
                "type": "boolean",
                "description": "Whether to add a Qwen watermark. Default false.",
            },
            "seed": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2147483647,
                "description": "Optional seed for partially reproducible generations.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
)

IMAGE_GENERATE_METADATA = ToolMetadata(
    label="Image Generate",
    category="media",
    side_effect=ToolSideEffect.NETWORK,
    parallel_safe=False,
    timeout_seconds=180.0,
    max_output_chars=5000,
)

