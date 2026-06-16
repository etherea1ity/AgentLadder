"""Capability registry used by the Klara harness."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import replace

import klara.capabilities.tools as tools_package
from klara.capabilities.base_tool import BaseTool, ToolTurnEffect
from klara.core.tools import KlaraTool, ToolResult


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

    def prompt_guidance(self) -> tuple[str, ...]:
        """Collect prompt guidance owned by visible tool classes."""

        guidance: list[str] = []
        for tool in self._tools:
            if not isinstance(tool, BaseTool):
                continue
            prompt = tool.prompt_guidance()
            if prompt and prompt.strip():
                guidance.append(prompt.strip())
        return tuple(guidance)

    def effects_for_results(self, results: list[ToolResult]) -> tuple[ToolTurnEffect, ...]:
        """Dispatch result callbacks back to their owning tool classes."""

        effects: list[ToolTurnEffect] = []
        tools_by_name = {
            tool.spec.name: tool for tool in self._tools if isinstance(tool, BaseTool)
        }
        for result in results:
            tool = tools_by_name.get(result.name)
            if tool is None:
                continue
            effect = tool.after_result(result)
            if effect is not None:
                effects.append(replace(effect, source_tool=tool.spec.name))
        return tuple(effects)


def discover_local_tools() -> list[KlaraTool]:
    """Discover concrete local tools from tool packages.

    Returns:
        Tool instances found under `klara.capabilities.tools`.
    """

    return [tool_class() for tool_class in discover_local_tool_classes()]


def discover_local_tool_classes() -> tuple[type[BaseTool], ...]:
    """Discover one `BaseTool` subclass from each concrete tool package."""

    discovered: list[type[BaseTool]] = []
    for module_info in sorted(
        pkgutil.iter_modules(tools_package.__path__, tools_package.__name__ + "."),
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
