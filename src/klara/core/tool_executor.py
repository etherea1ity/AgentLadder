"""Tool execution boundary for Klara core."""

from __future__ import annotations

from klara.core.tools import KlaraTool, ToolCall, ToolResult, ToolSpec


class ToolExecutor:
    """Resolve model-requested tool calls against visible tools.

    The executor is a narrow boundary: it knows concrete tools only through the
    `KlaraTool` protocol. It does not decide which tools should be visible; the
    harness and capability registry own that choice.
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
        if result.tool_call_id != call.id:
            # Normalize mismatched tool ids so the transcript joins request/result.
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=result.content,
                ok=result.ok,
                error=result.error,
            )
        return result
