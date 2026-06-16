from __future__ import annotations

from dataclasses import dataclass

from klara.core.tool_executor import ToolExecutor
from klara.core.tools import JsonObject, ToolCall, ToolMetadata, ToolResult, ToolSpec


@dataclass(frozen=True)
class LongOutputTool:
    """Tool fixture that proves executor-level output limiting."""

    # Spec keeps the fixture model-visible shape minimal.
    spec: ToolSpec = ToolSpec(
        name="long_output",
        description="Returns a long output for executor tests.",
        input_schema={"type": "object", "properties": {}},
    )
    # Metadata deliberately sets a tiny output cap for the truncation assertion.
    metadata: ToolMetadata = ToolMetadata(
        label="Long Output",
        category="test",
        max_output_chars=5,
    )

    def execute(self, arguments: JsonObject) -> ToolResult:
        """Return more text than the declared output limit permits."""

        return ToolResult(
            tool_call_id=str(arguments.get("tool_call_id", "tool-call")),
            name=self.spec.name,
            content="abcdefghij",
        )


def test_executor_exposes_tool_metadata_in_spec_order() -> None:
    """Executor should keep model specs and runtime metadata aligned."""

    executor = ToolExecutor([LongOutputTool()])

    assert [spec.name for spec in executor.specs] == ["long_output"]
    assert [metadata.label for metadata in executor.metadata] == ["Long Output"]


def test_executor_limits_model_visible_tool_output() -> None:
    """Executor should apply per-tool output limits before observations return."""

    executor = ToolExecutor([LongOutputTool()])
    call = ToolCall(id="long-1", name="long_output", arguments={})

    result = executor.execute(call)

    assert result.tool_call_id == "long-1"
    assert result.content == "abcde\n[tool output truncated after 5 characters]"
