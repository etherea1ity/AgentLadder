from __future__ import annotations

import threading
from dataclasses import dataclass

from klara.core.tool_executor import ToolExecutor
from klara.core.tools import JsonObject, ToolCall, ToolMetadata, ToolResult, ToolSpec


@dataclass(frozen=True)
class LongOutputTool:
    """Tool fixture that proves executor-level output limiting."""

    # Spec keeps the fixture model-visible shape compact.
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


class ParallelProbeTool:
    """Tool fixture that only succeeds when two calls run in the same wave."""

    # Spec lets both probe calls target the same model-visible tool name.
    spec: ToolSpec = ToolSpec(
        name="parallel_probe",
        description="Proves parallel-safe batch execution.",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
    )
    # Parallel-safe metadata allows ToolExecutor to group calls into one wave.
    metadata: ToolMetadata = ToolMetadata(
        label="Parallel Probe",
        category="test",
        parallel_safe=True,
    )

    def __init__(self, barrier: threading.Barrier) -> None:
        """Store the barrier used to prove concurrent execution."""

        # Both calls must reach this barrier before either can return.
        self._barrier = barrier

    def execute(self, arguments: JsonObject) -> ToolResult:
        """Wait for the sibling call, then return the provided value."""

        # A sequential executor would time out here, causing the assertion to fail.
        self._barrier.wait(timeout=1.0)
        return ToolResult(
            tool_call_id=str(arguments.get("tool_call_id", "tool-call")),
            name=self.spec.name,
            content=str(arguments.get("value", "")),
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


def test_executor_runs_parallel_safe_batch_and_preserves_order() -> None:
    """Parallel-safe calls should run together while results keep request order."""

    barrier = threading.Barrier(2)
    executor = ToolExecutor([ParallelProbeTool(barrier)])
    calls = (
        ToolCall(id="probe-1", name="parallel_probe", arguments={"value": "first"}),
        ToolCall(id="probe-2", name="parallel_probe", arguments={"value": "second"}),
    )

    results = executor.execute_many(calls)

    assert [result.tool_call_id for result in results] == ["probe-1", "probe-2"]
    assert [result.content for result in results] == ["first", "second"]
