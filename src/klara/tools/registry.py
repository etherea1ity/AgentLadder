"""Tool registry used by Klara run assembly."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import klara.tools.builtin as builtin_tools_package
from klara.core.tools import KlaraTool
from klara.tools.base import BaseTool


class ToolRegistry:
    """Store the tools visible to a Klara run.

    The registry starts small so toolsets, permissions, and visibility policy
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
    def with_default_tools(cls) -> "ToolRegistry":
        """Create the default local registry.

        Returns:
            A registry exposing discovered local tools in deterministic order.
        """

        return cls(discover_local_tools())

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


def discover_local_tools() -> list[KlaraTool]:
    """Discover concrete local tools from built-in tool packages.

    Returns:
        Tool instances found under `klara.tools.builtin`.
    """

    return [tool_class() for tool_class in discover_local_tool_classes()]


def discover_local_tool_classes() -> tuple[type[BaseTool], ...]:
    """Discover one `BaseTool` subclass from each concrete built-in tool package."""

    discovered: list[type[BaseTool]] = []
    for module_info in sorted(
        pkgutil.iter_modules(
            builtin_tools_package.__path__,
            builtin_tools_package.__name__ + ".",
        ),
        key=lambda item: item.name,
    ):
        if not module_info.ispkg:
            continue
        tool_module = importlib.import_module(f"{module_info.name}.tool")
        candidates = [
            value
            for _, value in inspect.getmembers(tool_module, inspect.isclass)
            if value is not BaseTool
            and issubclass(value, BaseTool)
            and value.__module__ == tool_module.__name__
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"{module_info.name}.tool must define exactly one BaseTool subclass"
            )
        discovered.append(candidates[0])
    return tuple(discovered)
