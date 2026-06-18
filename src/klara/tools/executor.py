"""Tool execution boundary for Klara runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from time import perf_counter

from klara.core.tools import (
    KlaraTool,
    ToolCall,
    ToolExecutionReport,
    ToolMetadata,
    ToolResult,
    ToolSpec,
)


class ToolExecutor:
    """Resolve model-requested tool calls against visible tools.

    The executor is a narrow boundary: it knows concrete tools only through the
    `KlaraTool` protocol. It does not decide which tools should be visible; the
    harness and tool registry own that choice.
    """

    def __init__(self, tools: list[KlaraTool] | None = None) -> None:
        """Create an executor from the tools visible in this run.

        Args:
            tools: Concrete tool implementations selected by the harness.
        """

        # Name lookup keeps model tool calls independent of concrete instances.
        self._tools = {tool.spec.name: tool for tool in tools or []}

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        """Return model-visible tool specifications.

        Returns:
            Tool specs that can be sent to the injected LLM client.
        """

        return tuple(tool.spec for tool in self._tools.values())

    @property
    def metadata(self) -> tuple[ToolMetadata, ...]:
        """Return Klara-visible tool metadata in model-spec order.

        Returns:
            Tool metadata used by planning, trace, UI, and guard layers.
        """

        return tuple(tool.metadata for tool in self._tools.values())

    def execute(self, call: ToolCall) -> ToolResult:
        """Execute one tool call and convert failures into observations.

        Args:
            call: Model-requested tool invocation.

        Returns:
            A tool result that can be appended as a tool observation message.
        """

        # Resolve the requested name against this run's visible tool set.
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content="",
                ok=False,
                error=f"Unknown tool: {call.name}",
            )
        try:
            # Tool exceptions become failed observations so the loop can continue.
            result = tool.execute(call.arguments)
        except Exception as exc:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content="",
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        # Normalize and limit results before exposing observations to the model.
        normalized = self._normalize_result(call, result)
        return self._limit_result(normalized, max_chars=tool.metadata.max_output_chars)

    def execute_many(self, calls: tuple[ToolCall, ...]) -> tuple[ToolResult, ...]:
        """Execute one model-requested tool batch in dependency-safe waves.

        Args:
            calls: Tool calls requested by one assistant turn.

        Returns:
            Tool results in the same order as the requested calls.
        """

        reports = self.execute_many_with_reports(calls)
        return tuple(report.result for report in reports)

    def execute_many_with_reports(
        self,
        calls: tuple[ToolCall, ...],
    ) -> tuple[ToolExecutionReport, ...]:
        """Execute one model-requested tool batch with per-call metrics.

        Args:
            calls: Tool calls requested by one assistant turn.

        Returns:
            Tool execution reports in the same order as the requested calls.
        """

        # Consecutive parallel-safe calls can share a wave; serial calls split waves.
        reports: list[ToolExecutionReport] = []
        parallel_wave: list[ToolCall] = []
        for call in calls:
            if self._can_run_in_parallel(call):
                parallel_wave.append(call)
                continue
            reports.extend(self._execute_parallel_report_wave(tuple(parallel_wave)))
            parallel_wave = []
            reports.append(self._execute_with_report(call))
        reports.extend(self._execute_parallel_report_wave(tuple(parallel_wave)))
        return tuple(reports)

    def _can_run_in_parallel(self, call: ToolCall) -> bool:
        """Return whether a tool call may run beside another call."""

        tool = self._tools.get(call.name)
        if tool is None:
            return False
        return tool.metadata.parallel_safe and not tool.metadata.requires_approval

    def _execute_parallel_wave(self, calls: tuple[ToolCall, ...]) -> tuple[ToolResult, ...]:
        """Execute a contiguous wave of parallel-safe tool calls."""

        reports = self._execute_parallel_report_wave(calls)
        return tuple(report.result for report in reports)

    def _execute_parallel_report_wave(
        self,
        calls: tuple[ToolCall, ...],
    ) -> tuple[ToolExecutionReport, ...]:
        """Execute a contiguous parallel-safe wave with per-call metrics."""

        if not calls:
            return ()
        if len(calls) == 1:
            return (self._execute_with_report(calls[0]),)
        # Thread pool keeps the sync tool interface simple while allowing I/O tools to overlap.
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return tuple(pool.map(self._execute_with_report, calls))

    def _execute_with_report(self, call: ToolCall) -> ToolExecutionReport:
        """Execute one tool call and attach timing metadata."""

        started_at = _now_iso()
        started = perf_counter()
        result = self.execute(call)
        duration_ms = int((perf_counter() - started) * 1000)
        completed_at = _now_iso()
        return ToolExecutionReport(
            call=call,
            result=result,
            duration_ms=duration_ms,
            started_at=started_at,
            completed_at=completed_at,
        )

    def _normalize_result(self, call: ToolCall, result: ToolResult) -> ToolResult:
        """Normalize a concrete result against the original model request."""

        if result.tool_call_id == call.id and result.name == call.name:
            return result
        # Normalize mismatched ids/names so the transcript joins request/result.
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content=result.content,
            ok=result.ok,
            error=result.error,
        )

    def _limit_result(self, result: ToolResult, *, max_chars: int) -> ToolResult:
        """Apply the tool's model-visible output limit."""

        if len(result.content) <= max_chars:
            return result
        # Truncate content at the declared boundary and make truncation explicit.
        content = result.content[:max_chars]
        error = result.error
        if result.error and len(result.error) > max_chars:
            error = result.error[:max_chars]
        return ToolResult(
            tool_call_id=result.tool_call_id,
            name=result.name,
            content=f"{content}\n[tool output truncated after {max_chars} characters]",
            ok=result.ok,
            error=error,
        )


def _now_iso() -> str:
    """Return an ISO timestamp for tool execution metrics."""

    return datetime.now(UTC).isoformat()
