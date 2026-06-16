"""Current-time capability used as the first real Klara tool template."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from klara.capabilities.base_tool import BaseTool
from klara.capabilities.tools.current_time.schema import CURRENT_TIME_METADATA, CURRENT_TIME_SPEC
from klara.capabilities.tools.current_time.timezones import format_utc_offset, resolve_timezone
from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec


@dataclass(frozen=True)
class CurrentTimeTool(BaseTool):
    """Return the current local or requested time as a model observation.

    This tool is the template for real local capabilities: it has a
    model-visible schema, Klara-visible runtime metadata, and one narrow
    execution method. It does not know the loop, frontend, provider, or trace.
    """

    # Spec is imported from schema.py so model contract stays easy to inspect.
    spec: ToolSpec = CURRENT_TIME_SPEC
    # Metadata is separate from the spec because it is never sent to the model.
    metadata: ToolMetadata = CURRENT_TIME_METADATA

    def run(self, arguments: JsonObject) -> ToolResult:
        """Return current time for the requested timezone.

        Args:
            arguments: JSON-like arguments with optional `timezone`.

        Returns:
            A tool observation containing compact JSON, or a failed observation
            when the requested timezone cannot be resolved.
        """

        timezone_name = str(arguments.get("timezone") or "").strip()
        try:
            resolved_name, resolved_timezone = resolve_timezone(timezone_name)
        except ValueError as exc:
            return self.failure(arguments, str(exc))

        # Timestamp fields stay explicit so the model need not parse prose.
        now = datetime.now(resolved_timezone)
        content = {
            "timezone": resolved_name,
            "iso": now.isoformat(timespec="seconds"),
            "date": now.date().isoformat(),
            "time": now.time().isoformat(timespec="seconds"),
            "weekday": now.strftime("%A"),
            "utc_offset": format_utc_offset(now),
        }
        return self.json_success(arguments, content)
