"""Public web search and page-fetch services for Klara tools."""

from __future__ import annotations

from klara.services.web.fetcher import FetchedPage, HttpDocument, WebFetchError, fetch_page
from klara.services.web.research import (
    EvidenceLedger,
    ResearchDecision,
    SearchCandidate,
    SourceRecord,
    WebResearchBudget,
    WebResearchController,
    WebResearchPolicy,
    WebResearchState,
)
from klara.services.web.search import SearchHit, SearchResponse, WebSearchError, search_web

__all__ = [
    "EvidenceLedger",
    "FetchedPage",
    "HttpDocument",
    "ResearchDecision",
    "SearchCandidate",
    "SearchHit",
    "SearchResponse",
    "SourceRecord",
    "WebResearchBudget",
    "WebResearchController",
    "WebFetchError",
    "WebResearchPolicy",
    "WebResearchState",
    "WebSearchError",
    "fetch_page",
    "search_web",
]

