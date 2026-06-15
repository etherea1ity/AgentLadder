from __future__ import annotations

from klara.core.tools import KlaraTool, ToolCall, ToolResult, ToolSpec


class ToolExecutor:
    def __init__(self, tools: list[KlaraTool] | None = None) -> None:
        self._tools = {tool.spec.name: tool for tool in tools or []}

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec for tool in self._tools.values())

    def execute(self, call: ToolCall) -> ToolResult:
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
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=result.content,
                ok=result.ok,
                error=result.error,
            )
        return result
