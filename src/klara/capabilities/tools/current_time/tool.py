"""Current-time capability used as the first real Klara tool template."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from klara.capabilities.tools.current_time.schema import CURRENT_TIME_METADATA, CURRENT_TIME_SPEC
from klara.capabilities.tools.current_time.timezones import format_utc_offset, resolve_timezone
from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec


@dataclass(frozen=True)
class CurrentTimeTool:
    """Return the current local or requested time as a model observation.

    This tool is the template for real local capabilities: it has a
    model-visible schema, Klara-visible runtime metadata, and one narrow
    execution method. It does not know the loop, frontend, provider, or trace.
    """

    # Spec is imported from schema.py so model contract stays easy to inspect.
    spec: ToolSpec = CURRENT_TIME_SPEC
    # Metadata is separate from the spec because it is never sent to the model.
    metadata: ToolMetadata = CURRENT_TIME_METADATA

    def execute(self, arguments: JsonObject) -> ToolResult:
        """Return current time for the requested timezone.

        Args:
            arguments: JSON-like arguments with optional `timezone`.

        Returns:
            A tool observation containing compact JSON, or a failed observation
            when the requested timezone cannot be resolved.
        """

        # The executor normalizes this fallback id to the actual tool call id.
        tool_call_id = str(arguments.get("tool_call_id", "tool-call"))
        timezone_name = str(arguments.get("timezone") or "").strip()
        try:
            resolved_name, resolved_timezone = resolve_timezone(timezone_name)
        except ValueError as exc:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=self.spec.name,
                content="",
                ok=False,
                error=str(exc),
            )

        # Timestamp fields stay explicit so the model need not parse prose.
        now = datetime.now(resolved_timezone)
        content = {
            "timezone": resolved_name,
            "iso": now.isoformat(timespec="seconds"),
            "date": now.date().isoformat(),
            "time": now.time().isoformat(timespec="seconds"),
            "utc_offset": format_utc_offset(now),
        }
        return ToolResult(
            tool_call_id=tool_call_id,
            name=self.spec.name,
            content=json.dumps(content, ensure_ascii=False),
        )
