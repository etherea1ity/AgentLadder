from __future__ import annotations

from klara.tools.base import BaseTool
from klara.tools.registry import ToolRegistry, discover_local_tool_classes


def test_tool_registry_discovers_builtin_tools_from_canonical_package() -> None:
    """Default runtime tools should come from the canonical tools package."""

    registry = ToolRegistry.with_default_tools()

    names = {tool.spec.name for tool in registry.visible_tools()}

    assert names == {
        "current_time",
        "evidence_submit",
        "image_generate",
        "web_fetch",
        "web_search",
    }


def test_canonical_builtin_tools_use_base_template() -> None:
    """Every canonical built-in tool should follow the shared authoring template."""

    classes = discover_local_tool_classes()

    assert classes
    assert all(issubclass(tool_class, BaseTool) for tool_class in classes)
