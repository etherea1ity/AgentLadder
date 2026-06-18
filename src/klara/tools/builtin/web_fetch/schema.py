"""Schema and runtime metadata for the web-fetch tool."""

from __future__ import annotations

from klara.core.tools import ToolMetadata, ToolOutputTrust, ToolSideEffect, ToolSpec


WEB_FETCH_SPEC = ToolSpec(
    name="web_fetch",
    description=(
        "Fetch one public HTTP(S) page and return readable text, final URL, "
        "status, content type, title, and truncation metadata."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Public http or https URL to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "minimum": 200,
                "maximum": 6000,
                "description": "Optional maximum page text characters to return.",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
)

WEB_FETCH_METADATA = ToolMetadata(
    label="Web Fetch",
    category="web",
    side_effect=ToolSideEffect.NETWORK,
    parallel_safe=True,
    timeout_seconds=10.0,
    max_output_chars=7000,
    output_trust=ToolOutputTrust.UNTRUSTED,
)

