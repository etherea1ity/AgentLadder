from __future__ import annotations

from klara.capabilities.base_tool import BaseTool
from klara.capabilities.registry import (
    CapabilityRegistry,
    discover_local_tool_classes,
)


def test_default_registry_discovers_local_tool_packages() -> None:
    """Default tools should come from package discovery, not a hand-written list."""

    registry = CapabilityRegistry.with_default_tools()

    names = {tool.spec.name for tool in registry.visible_tools()}

    assert names == {"current_time"}


def test_discovered_local_tools_use_base_template() -> None:
    """Every discovered tool should follow the shared authoring template."""

    classes = discover_local_tool_classes()

    assert classes
    assert all(issubclass(tool_class, BaseTool) for tool_class in classes)


def test_registry_collects_tool_owned_prompt_guidance() -> None:
    """Prompt guidance should be owned by visible tool classes."""

    registry = CapabilityRegistry.with_default_tools()

    guidance = "\n".join(registry.prompt_guidance())

    assert "Current time tool guidance" in guidance
    assert "current_time" in guidance
