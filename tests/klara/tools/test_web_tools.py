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
    assert payload["source_tier"] == "candidate_source"
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
    assert "ranked result cards" in tool.spec.description
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
    assert payload["observation_kind"] == "web_search_candidates"
    assert payload["evidence_status"] == "candidate_snippets_only"
    assert "web_fetch" in payload["next_step"]
    assert "not verified source text" in payload["next_step"]
    assert "may not enforce freshness or language hints" in payload["provider_limitations"]
    assert "preferred_source" in payload["source_selection"]
    assert payload["provider"] == "duckduckgo_lite"
    assert payload["results"] == [
        {
            "title": "Example",
            "url": "https://example.com",
            "snippet": "",
            "source_tier": "candidate_source",
            "original_rank": 1,
        }
    ]
    assert payload["trust"] == "untrusted_external_content"


def test_web_search_tool_marks_preferred_sources_without_losing_original_rank() -> None:
    """Known reliable domains should be easier for the model to choose."""

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
                SearchHit(title="SEO Site", url="https://example.com/worldcup"),
                SearchHit(title="BBC Scores", url="https://www.bbc.com/sport/football"),
            ),
            searched_url="https://lite.duckduckgo.com/lite/?q=worldcup",
            truncated=False,
        )

    tool = WebSearchTool(searcher=searcher)

    result = tool.execute({"query": "world cup scores", "count": 2})

    payload = json.loads(result.content)
    assert result.ok is True
    assert [hit["title"] for hit in payload["results"]] == ["BBC Scores", "SEO Site"]
    assert payload["results"][0]["source_tier"] == "preferred_source"
    assert payload["results"][0]["original_rank"] == 2
    assert payload["results"][1]["source_tier"] == "candidate_source"
    assert payload["results"][1]["original_rank"] == 1


def test_web_fetch_tool_marks_preferred_source_domains() -> None:
    """Fetched page observations should expose source quality too."""

    def page_fetcher(url: str, *, max_chars: int, timeout_seconds: float) -> FetchedPage:
        return FetchedPage(
            url=url,
            final_url="https://www.bbc.com/sport/football/world-cup",
            status=200,
            content_type="text/html",
            title="BBC",
            text="BBC source text",
            truncated=False,
        )

    tool = WebFetchTool(page_fetcher=page_fetcher)

    result = tool.execute({"url": "https://www.bbc.com/sport/football/world-cup"})

    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["source_tier"] == "preferred_source"


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
    assert captured_query == "2026 world cup summary after:2026-06-11 before:2026-06-18"
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
