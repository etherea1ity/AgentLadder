"""Capability registry used by the Klara harness."""

from __future__ import annotations

from klara.capabilities.tools.fake_tool import DebugEchoTool
from klara.core.tools import KlaraTool


class CapabilityRegistry:
    """Store the tools visible to a Klara run.

    The registry starts small so profiles, permissions, and visibility policy
    can be added without changing core loop contracts.
    """

    def __init__(self, tools: list[KlaraTool] | None = None) -> None:
        """Create a registry with optional initial tools.

        Args:
            tools: Concrete tool implementations visible to this registry.
        """

        # Tools remain ordered so model-visible specs have deterministic order.
        self._tools = list(tools or [])

    @classmethod
    def with_default_tools(cls) -> "CapabilityRegistry":
        """Create the default local registry.

        Returns:
            A registry exposing only the deterministic `debug_echo` tool.
        """

        return cls([DebugEchoTool()])

    def register_tool(self, tool: KlaraTool) -> None:
        """Add one visible tool to the registry.

        Args:
            tool: Concrete tool implementation to expose.
        """

        self._tools.append(tool)

    def visible_tools(self) -> tuple[KlaraTool, ...]:
        """Return tools that should be exposed to the current run.

        Returns:
            Ordered concrete tools for the harness to wrap in `ToolExecutor`.
        """

        return tuple(self._tools)
