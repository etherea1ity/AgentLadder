from __future__ import annotations

from dataclasses import dataclass

from klara.core.tools import JsonObject, ToolResult, ToolSpec


@dataclass(frozen=True)
class DebugEchoTool:
    spec: ToolSpec = ToolSpec(
        name="debug_echo",
        description="Echoes text for deterministic Chapter 1 loop tests.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
        },
    )

    def execute(self, arguments: JsonObject) -> ToolResult:
        return ToolResult(
            tool_call_id=str(arguments.get("tool_call_id", "tool-call")),
            name=self.spec.name,
            content=str(arguments.get("text", "")),
        )
