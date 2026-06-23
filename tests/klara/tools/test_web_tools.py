from __future__ import annotations

import json

from klara.core.tools import ToolOutputTrust, ToolSideEffect
from klara.services.web import FetchedPage, SearchHit, SearchResponse, WebFetchError
from klara.tools.builtin.web_fetch import WebFetchTool
from klara.tools.builtin.web_search import WebSearchTool


def test_web_fetch_tool_declares_network_untrusted_metadata() -> None:
    """Web fetch should expose network and trust metadata for later grounding."""

    tool = WebFetchTool()

    assert tool.spec.name == "web_fetch"
    assert tool.spec.input_schema["required"] == ["url"]
    assert tool.metadata.category == "web"
    assert tool.metadata.side_effect == ToolSideEffect.NETWORK
    assert tool.metadata.parallel_safe is True
    assert tool.spec.input_schema["properties"]["max_chars"]["maximum"] == 12000
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
    assert "source_tier" not in payload
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


def test_web_fetch_tool_supports_relevant_snippets() -> None:
    """Relevant snippet mode should extract windows around query terms."""

    def page_fetcher(url: str, *, max_chars: int, timeout_seconds: float) -> FetchedPage:
        return FetchedPage(
            url=url,
            final_url="https://www.reuters.com/world/recent-event-report",
            status=200,
            content_type="text/html",
            title="Reuters recent event report",
            text=(
                "Opening navigation. "
                + ("filler " * 120)
                + "England beat Croatia 4-2 in Dallas. "
                + ("more filler " * 120)
            ),
            truncated=False,
        )

    tool = WebFetchTool(page_fetcher=page_fetcher)

    result = tool.execute(
        {
            "url": "https://www.reuters.com/world/recent-event-report",
            "max_chars": 12000,
            "extract_mode": "relevant_snippets",
            "query_terms": ["England", "Croatia"],
        }
    )

    payload = json.loads(result.content)
    assert result.ok is True
    assert "England beat Croatia 4-2" in payload["text"]
    assert payload["extract_mode"] == "relevant_snippets"
    assert payload["query_terms"] == ["England", "Croatia"]
    assert payload["no_relevant_terms_found"] is False
    assert "source_quality" not in payload


def test_web_fetch_tool_marks_missing_relevant_terms() -> None:
    """Snippet mode should say when query terms were not found."""

    def page_fetcher(url: str, *, max_chars: int, timeout_seconds: float) -> FetchedPage:
        return FetchedPage(
            url=url,
            final_url=url,
            status=200,
            content_type="text/html",
            title="Schedule page",
            text="Today schedule list only.",
            truncated=False,
        )

    tool = WebFetchTool(page_fetcher=page_fetcher)

    result = tool.execute(
        {
            "url": "https://example.com/schedule",
            "extract_mode": "relevant_snippets",
            "query_terms": ["England"],
        }
    )

    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["text"] == "Today schedule list only."
    assert payload["no_relevant_terms_found"] is True


def test_web_search_tool_declares_network_untrusted_metadata() -> None:
    """Web search should expose network and trust metadata for later grounding."""

    tool = WebSearchTool()

    assert tool.spec.name == "web_search"
    assert "candidate result cards" in tool.spec.description
    assert "web_fetch" not in tool.spec.description
    assert tool.spec.input_schema["required"] == ["query"]
    assert "freshness" in tool.spec.input_schema["properties"]
    assert "date_after" in tool.spec.input_schema["properties"]
    assert "date_before" in tool.spec.input_schema["properties"]
    assert "language" in tool.spec.input_schema["properties"]
    assert tool.metadata.category == "web"
    assert tool.metadata.side_effect == ToolSideEffect.NETWORK
    assert tool.metadata.parallel_safe is True
    assert tool.metadata.output_trust == ToolOutputTrust.UNTRUSTED


def test_web_search_tool_returns_candidate_results() -> None:
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
    assert payload["observation_kind"] == "web_search_candidates"
    assert payload["evidence_status"] == "candidate_snippets_only"
    assert "next_step" not in payload
    assert "may not enforce freshness or language hints" in payload["provider_limitations"]
    assert "source_selection" not in payload
    assert payload["provider"] == "duckduckgo_lite"
    assert payload["results"] == [
        {
            "title": "Example",
            "url": "https://example.com",
            "snippet": "",
            "original_rank": 1,
        }
    ]
    assert payload["trust"] == "untrusted_external_content"


def test_web_search_tool_preserves_provider_order_for_generic_queries() -> None:
    """Generic search results should not be reordered by topic preferences."""

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
            results=(
                SearchHit(title="Package Mirror", url="https://example.com/python"),
                SearchHit(title="Python Docs", url="https://docs.python.org/3/"),
            ),
            searched_url="https://lite.duckduckgo.com/lite/?q=python",
            truncated=False,
        )

    tool = WebSearchTool(searcher=searcher)

    result = tool.execute({"query": "python docs", "count": 2})

    payload = json.loads(result.content)
    assert result.ok is True
    assert [hit["title"] for hit in payload["results"]] == ["Package Mirror", "Python Docs"]
    assert [hit["original_rank"] for hit in payload["results"]] == [1, 2]
    assert "ranked_for_current_topic" not in payload


def test_web_search_tool_preserves_provider_order_for_all_queries() -> None:
    """Search should not rerank results with domain-specific policy."""

    def searcher(
        query: str,
        *,
        allowed_domains: tuple[str, ...],
        blocked_domains: tuple[str, ...],
        count: int,
        timeout_seconds: float,
    ) -> SearchResponse:
        assert count == 3
        return SearchResponse(
            query=query,
            provider="duckduckgo_lite",
            results=(
                SearchHit(title="SEO Site", url="https://example-seo.com/recent-event"),
                SearchHit(title="Official schedule", url="https://official.example.com/schedule"),
                SearchHit(title="Reuters report", url="https://www.reuters.com/world/recent-event-report"),
            ),
            searched_url="https://lite.duckduckgo.com/lite/?q=recent-event",
            truncated=False,
        )

    tool = WebSearchTool(searcher=searcher)

    result = tool.execute({"query": "latest public event update", "count": 3})

    payload = json.loads(result.content)
    assert result.ok is True
    assert [hit["title"] for hit in payload["results"]] == [
        "SEO Site",
        "Official schedule",
        "Reuters report",
    ]
    assert [hit["original_rank"] for hit in payload["results"]] == [1, 2, 3]
    assert "ranked_for_current_topic" not in payload
    assert all("source_quality" not in hit for hit in payload["results"])


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
            "query": "2026 public event summary",
            "freshness": "week",
            "date_after": "2026-06-11",
            "date_before": "2026-06-18",
            "language": "en",
            "count": 1,
        }
    )

    payload = json.loads(result.content)
    assert result.ok is True
    assert captured_query == "2026 public event summary after:2026-06-11 before:2026-06-18"
    assert payload["original_query"] == "2026 public event summary"
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
