"""Public web search and page-fetch services for Klara tools."""

from __future__ import annotations

from klara.services.web.fetcher import FetchedPage, HttpDocument, WebFetchError, fetch_page
from klara.services.web.search import SearchHit, SearchResponse, WebSearchError, search_web
from klara.services.web.source_quality import (
    classify_source,
    is_preferred_for_current_sports,
)

__all__ = [
    "FetchedPage",
    "HttpDocument",
    "SearchHit",
    "SearchResponse",
    "WebFetchError",
    "WebSearchError",
    "classify_source",
    "fetch_page",
    "is_preferred_for_current_sports",
    "search_web",
]

