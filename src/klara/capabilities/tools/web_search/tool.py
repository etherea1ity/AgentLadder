"""Model-visible web search capability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from klara.capabilities.base_tool import BaseTool, ToolInputError
from klara.capabilities.tools.web_search.schema import WEB_SEARCH_METADATA, WEB_SEARCH_SPEC
from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec
from klara.services.web import SearchResponse, WebSearchError, search_web


Searcher = Callable[..., SearchResponse]


@dataclass(frozen=True)
class WebSearchTool(BaseTool):
    """Search the public web and return URLs for later fetching.

    This tool owns the schema and runtime metadata. Provider-specific search
    behavior stays in `klara.services.web` so later official providers can be
    added without changing core loop mechanics.
    """

    spec: ToolSpec = WEB_SEARCH_SPEC
    metadata: ToolMetadata = WEB_SEARCH_METADATA
    searcher: Searcher = search_web

    def run(self, arguments: JsonObject) -> ToolResult:
        """Run a public web search and return structured results.

        Args:
            arguments: JSON-like arguments with `query` and optional filters.

        Returns:
            A JSON observation with ranked search results, or a failed
            observation when the provider cannot be reached.
        """

        query = self.optional_string(arguments, "query")
        if not query:
            raise ToolInputError("query must not be empty")
        allowed_domains = _optional_string_tuple(arguments, "allowed_domains")
        blocked_domains = _optional_string_tuple(arguments, "blocked_domains")
        count = _optional_int(arguments, "count", default=8)
        if count < 1 or count > 8:
            raise ToolInputError("count must be between 1 and 8")

        try:
            response = self.searcher(
                query,
                allowed_domains=allowed_domains,
                blocked_domains=blocked_domains,
                count=count,
                timeout_seconds=self.metadata.timeout_seconds,
            )
        except WebSearchError as exc:
            return self.failure(arguments, str(exc))

        return self.json_success(
            arguments,
            {
                "query": response.query,
                "provider": response.provider,
                "result_count": len(response.results),
                "results": [
                    {"title": hit.title, "url": hit.url, "snippet": hit.snippet}
                    for hit in response.results
                ],
                "searched_url": response.searched_url,
                "truncated": response.truncated,
                "searched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "trust": "untrusted_external_content",
            },
        )


def _optional_string_tuple(arguments: JsonObject, key: str) -> tuple[str, ...]:
    """Read an optional list of non-empty strings."""

    value = arguments.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ToolInputError(f"{key} must be an array of strings")
    strings: list[str] = []
    # Validate each domain entry so provider filters stay deterministic.
    for item in value:
        if not isinstance(item, str):
            raise ToolInputError(f"{key} must be an array of strings")
        text = item.strip()
        if text:
            strings.append(text)
    return tuple(strings)


def _optional_int(arguments: JsonObject, key: str, *, default: int) -> int:
    """Read an optional integer argument."""

    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{key} must be an integer")
    return value
