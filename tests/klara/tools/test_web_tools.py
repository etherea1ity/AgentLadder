from __future__ import annotations

import json

from klara.core.tools import ToolOutputTrust, ToolSideEffect
from klara.services.web import FetchedPage, SearchHit, SearchResponse, WebFetchError
from klara.tools.builtin.web_fetch import WebFetchTool
from klara.tools.builtin.web_search import WebSearchTool


def test_web_fetch_tool_declares_network_untrusted_metadata() -> None:
    """Web fetch should expose network and trust metadata for later guards."""

    tool = WebFetchTool()

    assert tool.spec.name == "web_fetch"
    assert tool.spec.input_schema["required"] == ["url"]
    assert tool.metadata.category == "web"
    assert tool.metadata.side_effect == ToolSideEffect.NETWORK
    assert tool.metadata.parallel_safe is True
    assert tool.metadata.output_trust == ToolOutputTrust.UNTRUSTED


def test_web_fetch_tool_returns_page_observation() -> None:
    """Web fetch should wrap service output as compact JSON."""

    def page_fetcher(url: str, *, max_chars: int, timeout_seconds: float) -> FetchedPage:
        return FetchedPage(
            url=url,
            final_url=f"{url}?final=1",
            status=200,
            content_type="text/html",
            title="Fetched",
            text="Page text",
            truncated=False,
        )

    tool = WebFetchTool(page_fetcher=page_fetcher)

    result = tool.execute({"url": "https://example.com", "max_chars": 500})

    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["title"] == "Fetched"
    assert payload["text"] == "Page text"
    assert payload["trust"] == "untrusted_external_content"


def test_web_fetch_tool_returns_failed_observation_for_fetch_errors() -> None:
    """Service fetch errors should become model-visible tool failures."""

    def page_fetcher(url: str, *, max_chars: int, timeout_seconds: float) -> FetchedPage:
        raise WebFetchError("URL must use http or https")

    tool = WebFetchTool(page_fetcher=page_fetcher)

    result = tool.execute({"url": "file:///secret.txt"})

    assert result.ok is False
    assert result.content == ""
    assert result.error == "URL must use http or https"


def test_web_search_tool_declares_network_untrusted_metadata() -> None:
    """Web search should expose network and trust metadata for later guards."""

    tool = WebSearchTool()

    assert tool.spec.name == "web_search"
    assert "live/current/latest/today/news/sports" in tool.spec.description
    assert "web_fetch" in tool.spec.description
    assert "untrusted" in tool.spec.description
    assert tool.spec.input_schema["required"] == ["query"]
    assert "freshness" in tool.spec.input_schema["properties"]
    assert "date_after" in tool.spec.input_schema["properties"]
    assert "date_before" in tool.spec.input_schema["properties"]
    assert "language" in tool.spec.input_schema["properties"]
    assert tool.metadata.category == "web"
    assert tool.metadata.side_effect == ToolSideEffect.NETWORK
    assert tool.metadata.parallel_safe is True
    assert tool.metadata.output_trust == ToolOutputTrust.UNTRUSTED


def test_web_search_tool_returns_ranked_results() -> None:
    """Web search should keep search and page reading separate."""

    def searcher(
        query: str,
        *,
        allowed_domains: tuple[str, ...],
        blocked_domains: tuple[str, ...],
        count: int,
        timeout_seconds: float,
    ) -> SearchResponse:
        return SearchResponse(
            query=query,
            provider="duckduckgo_lite",
            results=(SearchHit(title="Example", url="https://example.com"),),
            searched_url="https://lite.duckduckgo.com/lite/?q=example",
            truncated=False,
        )

    tool = WebSearchTool(searcher=searcher)

    result = tool.execute({"query": "example", "count": 1})

    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["provider"] == "duckduckgo_lite"
    assert payload["results"] == [
        {"title": "Example", "url": "https://example.com", "snippet": ""}
    ]
    assert payload["trust"] == "untrusted_external_content"


def test_web_search_tool_applies_portable_search_hints() -> None:
    """Web search should make date/freshness hints visible and provider-portable."""

    captured_query = ""

    def searcher(
        query: str,
        *,
        allowed_domains: tuple[str, ...],
        blocked_domains: tuple[str, ...],
        count: int,
        timeout_seconds: float,
    ) -> SearchResponse:
        nonlocal captured_query
        captured_query = query
        return SearchResponse(
            query=query,
            provider="duckduckgo_lite",
            results=(SearchHit(title="Recent", url="https://example.com/recent"),),
            searched_url="https://lite.duckduckgo.com/lite/?q=recent",
            truncated=False,
        )

    tool = WebSearchTool(searcher=searcher)

    result = tool.execute(
        {
            "query": "2026 world cup summary",
            "freshness": "week",
            "date_after": "2026-06-11",
            "date_before": "2026-06-18",
            "language": "en",
            "count": 1,
        }
    )

    payload = json.loads(result.content)
    assert result.ok is True
    assert captured_query == (
        "2026 world cup summary past week "
        "after:2026-06-11 before:2026-06-18 language:en"
    )
    assert payload["original_query"] == "2026 world cup summary"
    assert payload["effective_query"] == captured_query
    assert payload["search_hints"] == {
        "freshness": "week",
        "date_after": "2026-06-11",
        "date_before": "2026-06-18",
        "language": "en",
    }


def test_web_search_tool_rejects_invalid_search_hints() -> None:
    """Invalid freshness and date hints should become tool errors."""

    tool = WebSearchTool()

    result = tool.execute({"query": "example", "freshness": "hour"})

    assert result.ok is False
    assert result.error == "freshness must be day, week, month, or year"

    result = tool.execute({"query": "example", "date_after": "06/18/2026"})

    assert result.ok is False
    assert result.error == "date_after must use YYYY-MM-DD"
