"""Model-visible web page fetch capability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from klara.tools.base import BaseTool, ToolInputError
from klara.tools.builtin.web_fetch.schema import WEB_FETCH_METADATA, WEB_FETCH_SPEC
from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec
from klara.services.web import FetchedPage, WebFetchError, fetch_page
from klara.services.web.source_quality import (
    classify_source,
    is_preferred_for_current_sports,
)


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
        if max_chars < 200 or max_chars > 12000:
            raise ToolInputError("max_chars must be between 200 and 12000")
        query_terms = _optional_string_list(arguments, "query_terms")
        extract_mode = _optional_extract_mode(arguments)

        try:
            page = self.page_fetcher(
                url,
                max_chars=max_chars,
                timeout_seconds=self.metadata.timeout_seconds,
            )
        except WebFetchError as exc:
            return self.failure(arguments, str(exc))
        text, no_relevant_terms_found = _extract_text(
            page.text,
            query_terms=query_terms,
            extract_mode=extract_mode,
            max_chars=max_chars,
        )
        source_quality = classify_source(page.final_url or page.url, page.title)

        return self.json_success(
            arguments,
            {
                "url": page.url,
                "final_url": page.final_url,
                "status": page.status,
                "content_type": page.content_type,
                "title": page.title,
                "text": text,
                "truncated": page.truncated,
                "extract_mode": extract_mode,
                "query_terms": query_terms,
                "no_relevant_terms_found": no_relevant_terms_found,
                "source_quality": source_quality,
                "is_preferred_for_current_sports": is_preferred_for_current_sports(
                    source_quality
                ),
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


def _optional_string_list(arguments: JsonObject, key: str) -> list[str]:
    """Read an optional list of non-empty strings."""

    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolInputError(f"{key} must be an array of strings")
    terms: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ToolInputError(f"{key} must be an array of strings")
        text = " ".join(item.split())
        if text:
            terms.append(text)
    return terms[:16]


def _optional_extract_mode(arguments: JsonObject) -> str:
    """Read the optional extraction mode."""

    value = arguments.get("extract_mode")
    if value is None:
        return "plain"
    if not isinstance(value, str):
        raise ToolInputError("extract_mode must be a string")
    mode = value.strip()
    if mode not in {"plain", "relevant_snippets"}:
        raise ToolInputError("extract_mode must be plain or relevant_snippets")
    return mode


def _extract_text(
    text: str,
    *,
    query_terms: list[str],
    extract_mode: str,
    max_chars: int,
) -> tuple[str, bool]:
    """Return plain text or term-centered snippets."""

    if extract_mode != "relevant_snippets":
        return text, False
    snippets = _relevant_snippets(text, query_terms=query_terms, max_chars=max_chars)
    if snippets:
        return snippets, False
    return text[:max_chars].rstrip(), True


def _relevant_snippets(text: str, *, query_terms: list[str], max_chars: int) -> str:
    """Extract compact windows around requested query terms."""

    if not query_terms:
        return ""
    lowered = text.lower()
    windows: list[tuple[int, int]] = []
    window_radius = max(220, min(700, max_chars // 4))
    for term in query_terms:
        index = lowered.find(term.lower())
        if index < 0:
            continue
        windows.append((max(0, index - window_radius), min(len(text), index + len(term) + window_radius)))
    if not windows:
        return ""
    merged = _merge_windows(sorted(windows))
    parts = [" ".join(text[start:end].split()) for start, end in merged]
    return "\n\n---\n\n".join(part for part in parts if part)[:max_chars].rstrip()


def _merge_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping snippet windows."""

    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if not merged or start > merged[-1][1] + 40:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged

