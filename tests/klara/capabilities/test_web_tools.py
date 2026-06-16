from __future__ import annotations

import json

from klara.capabilities.tools.web_fetch import WebFetchTool
from klara.capabilities.tools.web_search import WebSearchTool
from klara.core.tools import ToolOutputTrust, ToolSideEffect
from klara.services.web import FetchedPage, SearchHit, SearchResponse, WebFetchError


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
    assert tool.spec.input_schema["required"] == ["query"]
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
