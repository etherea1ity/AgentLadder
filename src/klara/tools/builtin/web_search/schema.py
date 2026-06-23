"""Schema and runtime metadata for the web-search tool."""

from __future__ import annotations

from klara.core.tools import ToolMetadata, ToolOutputTrust, ToolSideEffect, ToolSpec


WEB_SEARCH_SPEC = ToolSpec(
    name="web_search",
    description=(
        "Search the public web and return candidate result cards as public "
        "links with titles, URLs, snippets, provider, and searched_at metadata."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query text.",
            },
            "allowed_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional domains that results must match.",
            },
            "blocked_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional domains to exclude from results.",
            },
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Optional maximum result count.",
            },
            "freshness": {
                "type": "string",
                "enum": ["day", "week", "month", "year", "any"],
                "description": "Optional freshness hint: day, week, month, year, or any.",
            },
            "date_after": {
                "type": "string",
                "description": "Optional YYYY-MM-DD hint for results after this date.",
            },
            "date_before": {
                "type": "string",
                "description": "Optional YYYY-MM-DD hint for results before this date.",
            },
            "language": {
                "type": "string",
                "description": "Optional ISO language hint.",
            },
            "country": {
                "type": "string",
                "description": "Optional ISO country hint.",
            },
            "search_depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "description": "Optional search-depth hint for providers that support it.",
            },
            "require_freshness_enforced": {
                "type": "boolean",
                "description": "Require a provider that can enforce freshness hints.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)

WEB_SEARCH_METADATA = ToolMetadata(
    label="Web Search",
    category="web",
    side_effect=ToolSideEffect.NETWORK,
    parallel_safe=True,
    timeout_seconds=10.0,
    max_output_chars=7000,
    output_trust=ToolOutputTrust.UNTRUSTED,
)

