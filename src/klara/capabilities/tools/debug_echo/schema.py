"""Schema and runtime metadata for the debug echo tool."""

from __future__ import annotations

from klara.core.tools import ToolMetadata, ToolSideEffect, ToolSpec


# The spec is intentionally tiny so tests can script tool calls directly.
DEBUG_ECHO_SPEC = ToolSpec(
    name="debug_echo",
    description="Echoes text for deterministic loop tests.",
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
        "required": ["text"],
    },
)

# The debug tool has no side effects and is safe to run alongside reads.
DEBUG_ECHO_METADATA = ToolMetadata(
    label="Debug Echo",
    category="debug",
    side_effect=ToolSideEffect.NONE,
    parallel_safe=True,
    max_output_chars=1000,
)
