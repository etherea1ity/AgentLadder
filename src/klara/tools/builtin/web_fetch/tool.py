"""Model-visible web page fetch capability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from klara.tools.base import BaseTool, ToolInputError
from klara.tools.builtin.web_fetch.schema import WEB_FETCH_METADATA, WEB_FETCH_SPEC
from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec
from klara.services.web import FetchedPage, WebFetchError, fetch_page


PageFetcher = Callable[..., FetchedPage]


@dataclass(frozen=True)
class WebFetchTool(BaseTool):
    """Fetch readable text from one public web page.

    This tool owns the model-facing contract and wraps the web service boundary.
    It does not decide provider policy, loop behavior, or frontend projection.
    """

    spec: ToolSpec = WEB_FETCH_SPEC
    metadata: ToolMetadata = WEB_FETCH_METADATA
    page_fetcher: PageFetcher = fetch_page

    def run(self, arguments: JsonObject) -> ToolResult:
        """Fetch one public page and return a structured observation.

        Args:
            arguments: JSON-like arguments with `url` and optional `max_chars`.

        Returns:
            A JSON observation with readable page text, or a failed observation
            when the URL cannot be fetched safely.
        """

        url = self.optional_string(arguments, "url")
        if not url:
            raise ToolInputError("url must not be empty")
        max_chars = _optional_int(arguments, "max_chars", default=4000)
        if max_chars < 200 or max_chars > 6000:
            raise ToolInputError("max_chars must be between 200 and 6000")

        try:
            page = self.page_fetcher(
                url,
                max_chars=max_chars,
                timeout_seconds=self.metadata.timeout_seconds,
            )
        except WebFetchError as exc:
            return self.failure(arguments, str(exc))

        return self.json_success(
            arguments,
            {
                "url": page.url,
                "final_url": page.final_url,
                "status": page.status,
                "content_type": page.content_type,
                "title": page.title,
                "text": page.text,
                "truncated": page.truncated,
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "trust": "untrusted_external_content",
            },
        )


def _optional_int(arguments: JsonObject, key: str, *, default: int) -> int:
    """Read an optional integer argument."""

    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{key} must be an integer")
    return value

