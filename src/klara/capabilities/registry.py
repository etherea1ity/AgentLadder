from __future__ import annotations

from klara.core.tools import KlaraTool


class CapabilityRegistry:
    def __init__(self, tools: list[KlaraTool] | None = None) -> None:
        self._tools = list(tools or [])

    def register_tool(self, tool: KlaraTool) -> None:
        self._tools.append(tool)

    def visible_tools(self) -> tuple[KlaraTool, ...]:
        return tuple(self._tools)
