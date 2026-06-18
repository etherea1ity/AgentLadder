"""Base class and helpers for authoring Klara tools."""

from __future__ import annotations

import json
from typing import Any

from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec


class ToolInputError(ValueError):
    """Raised when model-provided tool arguments are invalid."""


class BaseTool:
    """Lightweight authoring template for concrete Klara tools.

    Core only requires the structural `KlaraTool` protocol. Concrete local
    tools inherit this class to share argument helpers and result construction
    without making the runtime depend on an inheritance tree.
    """

    spec: ToolSpec
    metadata: ToolMetadata

    def execute(self, arguments: JsonObject) -> ToolResult:
        """Execute this tool and convert input errors into observations."""

        try:
            return self.run(arguments)
        except ToolInputError as exc:
            return self.failure(arguments, str(exc))

    def run(self, arguments: JsonObject) -> ToolResult:
        """Run the concrete tool implementation."""

        raise NotImplementedError

    def call_id(self, arguments: JsonObject) -> str:
        """Return the tool-call id embedded by the executor or a test fallback."""

        return str(arguments.get("tool_call_id", "tool-call"))

    def success(self, arguments: JsonObject, content: str) -> ToolResult:
        """Build a successful model-visible observation."""

        return ToolResult(
            tool_call_id=self.call_id(arguments),
            name=self.spec.name,
            content=content,
        )

    def json_success(self, arguments: JsonObject, content: dict[str, Any]) -> ToolResult:
        """Build a successful JSON observation."""

        return self.success(arguments, json.dumps(content, ensure_ascii=False))

    def failure(self, arguments: JsonObject, error: str) -> ToolResult:
        """Build a failed model-visible observation."""

        return ToolResult(
            tool_call_id=self.call_id(arguments),
            name=self.spec.name,
            content="",
            ok=False,
            error=error,
        )

    def optional_string(self, arguments: JsonObject, key: str) -> str:
        """Read an optional string argument, trimming surrounding whitespace."""

        value = arguments.get(key)
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ToolInputError(f"{key} must be a string")
        return value.strip()
