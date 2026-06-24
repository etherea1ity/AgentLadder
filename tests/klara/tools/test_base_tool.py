from __future__ import annotations

import json
from dataclasses import dataclass

from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec
from klara.tools.base import BaseTool, ToolInputError


@dataclass(frozen=True)
class TemplateProbeTool(BaseTool):
    """Tool fixture that exercises the shared BaseTool authoring template."""

    # Spec gives the fixture the same structural shape as a concrete local tool.
    spec: ToolSpec = ToolSpec(
        name="template_probe",
        description="Echoes values for BaseTool contract tests.",
        input_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "text": {"type": "string"},
            },
        },
    )
    # Metadata is intentionally plain because these tests focus on BaseTool.
    metadata: ToolMetadata = ToolMetadata(label="Template Probe", category="test")

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return values through each BaseTool helper under test."""

        mode = self.optional_string(arguments, "mode")
        if mode == "input_error":
            raise ToolInputError("invalid probe arguments")
        if mode == "json":
            return self.json_success(arguments, {"message": "Klara will keep going"})
        return self.success(arguments, self.optional_string(arguments, "text"))


def test_base_tool_converts_input_errors_into_failed_observations() -> None:
    """ToolInputError should become a failed observation, not a Python crash."""

    tool = TemplateProbeTool()

    result = tool.execute({"tool_call_id": "call-1", "mode": "input_error"})

    assert result.tool_call_id == "call-1"
    assert result.name == "template_probe"
    assert result.ok is False
    assert result.content == ""
    assert result.error == "invalid probe arguments"


def test_base_tool_json_success_keeps_utf8_content_readable() -> None:
    """JSON observations should keep UTF-8 text readable for traces and docs."""

    tool = TemplateProbeTool()

    result = tool.execute({"tool_call_id": "call-2", "mode": "json"})

    assert "Klara will keep going" in result.content
    assert json.loads(result.content) == {"message": "Klara will keep going"}


def test_base_tool_optional_string_trims_and_rejects_non_strings() -> None:
    """Optional string arguments should be narrow and predictable."""

    tool = TemplateProbeTool()

    trimmed = tool.execute({"tool_call_id": "call-3", "text": "  hello  "})
    rejected = tool.execute({"tool_call_id": "call-4", "text": 123})

    assert trimmed.content == "hello"
    assert rejected.ok is False
    assert rejected.error == "text must be a string"
