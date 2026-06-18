from __future__ import annotations

import json

from klara.core.tools import ToolOutputTrust, ToolSideEffect
from klara.tools.builtin.current_time import CurrentTimeTool


def test_current_time_tool_declares_real_tool_template_metadata() -> None:
    """Current time should be the first real tool-template example."""

    tool = CurrentTimeTool()

    assert tool.spec.name == "current_time"
    assert "exact current wall-clock" in tool.spec.description
    assert "web_search" not in tool.spec.description
    assert "timezone" in tool.spec.input_schema["properties"]
    assert tool.spec.input_schema["additionalProperties"] is False
    assert tool.metadata.label == "Current Time"
    assert tool.metadata.category == "time"
    assert tool.metadata.side_effect == ToolSideEffect.NONE
    assert tool.metadata.parallel_safe is True
    assert tool.metadata.output_trust == ToolOutputTrust.TRUSTED


def test_current_time_tool_returns_json_observation_for_known_timezone() -> None:
    """Current time should return structured JSON for model-visible use."""

    tool = CurrentTimeTool()

    result = tool.execute({"timezone": "Asia/Shanghai"})

    payload = json.loads(result.content)
    assert result.ok is True
    assert result.name == "current_time"
    assert payload["timezone"] == "Asia/Shanghai"
    assert payload["utc_offset"] == "+08:00"
    assert payload["weekday"]
    assert "T" in payload["iso"]


def test_current_time_tool_returns_failed_observation_for_unknown_timezone() -> None:
    """Unknown timezones should become tool errors, not Python exceptions."""

    tool = CurrentTimeTool()

    result = tool.execute({"timezone": "Mars/Olympus"})

    assert result.ok is False
    assert result.content == ""
    assert result.error == "Unknown timezone: Mars/Olympus"
