"""Deterministic demonstration tool for minimal loop tests."""

from __future__ import annotations

from dataclasses import dataclass

from klara.core.tools import JsonObject, ToolResult, ToolSpec


@dataclass(frozen=True)
class DebugEchoTool:
    """Echo text so tests can prove tool observation flow.

    This is not a real product capability. It exists only to make tool-call
    mechanics deterministic in tests and examples.
    """

    # Spec is model-visible and small enough for deterministic fake LLM paths.
    spec: ToolSpec = ToolSpec(
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

    def execute(self, arguments: JsonObject) -> ToolResult:
        """Return the requested text as a tool observation.

        Args:
            arguments: JSON-like arguments expected to contain `text`.

        Returns:
            A successful tool result with the echoed text.
        """

        # The fallback id keeps the fake tool usable in direct unit tests.
        return ToolResult(
            tool_call_id=str(arguments.get("tool_call_id", "tool-call")),
            name=self.spec.name,
            content=str(arguments.get("text", "")),
        )
