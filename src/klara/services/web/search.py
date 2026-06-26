"""Public web search service with configurable provider fallback."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from html import unescape
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import parse_qsl, quote_plus, urlparse
from urllib.request import Request, urlopen

from klara.infra.config.env import get_env_secret
from klara.services.web.fetcher import DEFAULT_TIMEOUT_SECONDS, HttpDocument, read_http_text
from klara.services.web.safety import host_matches_domain_list


DEFAULT_RESULT_COUNT = 20
DEFAULT_SEARCH_MAX_BYTES = 300_000
DUCKDUCKGO_HTML_URL = "https://lite.duckduckgo.com/lite/"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
DEFAULT_PROVIDER_ORDER = ("duckduckgo_lite", "tavily", "serpapi")


class WebSearchError(RuntimeError):
    """Raised when web search cannot produce a model-visible observation."""


@dataclass(frozen=True)
class SearchHit:
    """One normalized web search result."""

    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class SearchResponse:
    """Search results plus provider metadata."""

    query: str
    provider: str
    results: tuple[SearchHit, ...]
    searched_url: str
    truncated: bool
    provider_attempts: tuple[dict[str, object], ...] = ()
    freshness_enforced: bool = False


ReadSearchPage = Callable[..., HttpDocument]


@dataclass(frozen=True)
class AnchorCandidate:
    """Raw anchor data extracted from an HTML page."""

    href: str
    text: str


class AnchorExtractor(HTMLParser):
    """Extract anchors, optionally restricted to a CSS class name."""

    def __init__(self, *, required_class: str | None = None) -> None:
        """Create an anchor extractor.

        Args:
            required_class: Optional class name that must be present on anchors.
        """

        super().__init__(convert_charrefs=True)
        self.required_class = required_class
        self.anchors: list[AnchorCandidate] = []
        self._active_href: str | None = None
        self._active_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Begin capturing an anchor when it matches the requested class."""

        if tag.lower() != "a" or self._active_href is not None:
            return
        attributes = {name.lower(): value or "" for name, value in attrs}
        href = attributes.get("href", "").strip()
        if not href:
            return
        class_names = set(attributes.get("class", "").split())
        if self.required_class is not None and self.required_class not in class_names:
            return
        self._active_href = href
        self._active_text = []

    def handle_endtag(self, tag: str) -> None:
        """Finish capturing the active anchor."""

        if tag.lower() != "a" or self._active_href is None:
            return
        text = " ".join(" ".join(self._active_text).split())
        self.anchors.append(AnchorCandidate(href=self._active_href, text=text))
        self._active_href = None
        self._active_text = []

    def handle_data(self, data: str) -> None:
        """Collect visible text inside the active anchor."""

        if self._active_href is not None:
            self._active_text.append(data)


class ClassTextExtractor(HTMLParser):
    """Extract compact text from elements that match any requested class."""

    def __init__(self, *, class_names: tuple[str, ...]) -> None:
        """Create a class-based text extractor.

        Args:
            class_names: Class names whose element text should be captured.
        """

        super().__init__(convert_charrefs=True)
        self.class_names = set(class_names)
        self.texts: list[str] = []
        self._is_capturing = False
        self._capture_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Begin or deepen text capture for matching elements."""

        if self._is_capturing:
            self._capture_depth += 1
            return
        attributes = {name.lower(): value or "" for name, value in attrs}
        element_classes = set(attributes.get("class", "").split())
        if self.class_names.intersection(element_classes):
            self._is_capturing = True
            self._capture_depth = 0
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        """Finish text capture when the matching element closes."""

        if not self._is_capturing:
            return
        if self._capture_depth > 0:
            self._capture_depth -= 1
            return
        text = " ".join(" ".join(self._parts).split())
        if text:
            self.texts.append(text)
        self._is_capturing = False
        self._parts = []

    def handle_data(self, data: str) -> None:
        """Collect text inside a matching element."""

        if self._is_capturing:
            self._parts.append(data)


def search_web(
    query: str,
    *,
    allowed_domains: tuple[str, ...] = (),
    blocked_domains: tuple[str, ...] = (),
    count: int = DEFAULT_RESULT_COUNT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    freshness: str = "",
    search_depth: str = "basic",
    reader: ReadSearchPage = read_http_text,
) -> SearchResponse:
    """Search the public web with configured providers.

    Args:
        query: Search query text.
        allowed_domains: Optional domains that results must match.
        blocked_domains: Optional domains that results must not match.
        count: Maximum number of returned results.
        timeout_seconds: Network timeout for the search request.
        reader: Optional test seam for supplying search-result HTML.

    Returns:
        Normalized search response.

    Raises:
        WebSearchError: If arguments are invalid or the provider fails.
    """

    normalized_query = " ".join(query.split())
    if not normalized_query:
        raise WebSearchError("query must not be empty")
    if count < 1 or count > DEFAULT_RESULT_COUNT:
        raise WebSearchError(f"count must be between 1 and {DEFAULT_RESULT_COUNT}")

    attempts: list[dict[str, object]] = []
    providers = _provider_order()

    for provider in providers:
        try:
            if provider == "duckduckgo_lite":
                response = search_duckduckgo_lite(
                    normalized_query,
                    allowed_domains=allowed_domains,
                    blocked_domains=blocked_domains,
                    count=count,
                    timeout_seconds=timeout_seconds,
                    reader=reader,
                )
            elif provider == "tavily":
                response = search_tavily(
                    normalized_query,
                    allowed_domains=allowed_domains,
                    blocked_domains=blocked_domains,
                    count=count,
                    timeout_seconds=timeout_seconds,
                    freshness=freshness,
                    search_depth=search_depth,
                )
            elif provider == "serpapi":
                response = search_serpapi(
                    normalized_query,
                    allowed_domains=allowed_domains,
                    blocked_domains=blocked_domains,
                    count=count,
                    timeout_seconds=timeout_seconds,
                )
            else:
                attempts.append(
                    {
                        "provider": provider,
                        "ok": False,
                        "failure_type": "unsupported_provider",
                    }
                )
                continue
        except WebSearchError as exc:
            attempts.append(
                {
                    "provider": provider,
                    "ok": False,
                    "failure_type": _failure_type(str(exc)),
                    "error": str(exc),
                }
            )
            continue
        attempts.append({"provider": provider, "ok": True})
        return SearchResponse(
            query=response.query,
            provider=response.provider,
            results=response.results,
            searched_url=response.searched_url,
            truncated=response.truncated,
            provider_attempts=tuple(attempts),
            freshness_enforced=response.freshness_enforced,
        )

    if not attempts:
        raise WebSearchError("no search provider is configured")
    details = "; ".join(
        f"{attempt['provider']}={attempt.get('failure_type', 'failed')}"
        for attempt in attempts
    )
    raise WebSearchError(f"all search providers failed: {details}")


def search_duckduckgo_lite(
    query: str,
    *,
    allowed_domains: tuple[str, ...] = (),
    blocked_domains: tuple[str, ...] = (),
    count: int = DEFAULT_RESULT_COUNT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    reader: ReadSearchPage = read_http_text,
) -> SearchResponse:
    """Search DuckDuckGo Lite and parse public result links."""

    search_url = f"{DUCKDUCKGO_HTML_URL}?q={quote_plus(query)}"
    try:
        document = reader(
            search_url,
            timeout_seconds=timeout_seconds,
            max_bytes=DEFAULT_SEARCH_MAX_BYTES,
        )
    except Exception as exc:
        raise WebSearchError(str(exc)) from exc

    if _looks_like_challenge_page(document.text):
        raise WebSearchError("anti_bot_challenge")

    hits = parse_duckduckgo_results(document.text)
    if not hits:
        hits = parse_generic_links(document.text)
    hits = _filter_hits(
        hits,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )
    hits = _dedupe_hits(hits)
    return SearchResponse(
        query=query,
        provider="duckduckgo_lite",
        results=tuple(hits[:count]),
        searched_url=document.final_url,
        truncated=document.truncated,
    )


def search_tavily(
    query: str,
    *,
    allowed_domains: tuple[str, ...] = (),
    blocked_domains: tuple[str, ...] = (),
    count: int = DEFAULT_RESULT_COUNT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    freshness: str = "",
    search_depth: str = "basic",
) -> SearchResponse:
    """Search Tavily's official API and normalize result cards."""

    api_key = get_env_secret("TAVILY_API_KEY", dotenv_path=".env").strip()
    if not api_key:
        raise WebSearchError("provider_not_configured")

    request_payload: dict[str, object] = {
        "query": query,
        "search_depth": search_depth or "basic",
        "max_results": count,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_image_descriptions": False,
    }
    if freshness and freshness != "any":
        request_payload["topic"] = "news"
        request_payload["time_range"] = freshness
    if allowed_domains:
        request_payload["include_domains"] = list(allowed_domains)
    if blocked_domains:
        request_payload["exclude_domains"] = list(blocked_domains)

    body = json.dumps(request_payload).encode("utf-8")
    request = Request(
        TAVILY_SEARCH_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "KlaraAgentLadder/0.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read(DEFAULT_SEARCH_MAX_BYTES + 1)
            status = response.getcode()
    except Exception as exc:
        raise WebSearchError(f"tavily_request_failed: {exc}") from exc

    truncated = len(response_body) > DEFAULT_SEARCH_MAX_BYTES
    response_body = response_body[:DEFAULT_SEARCH_MAX_BYTES]
    try:
        payload = json.loads(response_body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise WebSearchError("tavily_invalid_json") from exc
    if status is not None and status >= 400:
        raise WebSearchError(f"tavily_http_{status}")
    if not isinstance(payload, dict):
        raise WebSearchError("tavily_invalid_payload")

    raw_results = payload.get("results", [])
    if not isinstance(raw_results, list):
        raise WebSearchError("tavily_invalid_results")
    hits: list[SearchHit] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("content") or "").strip()
        if title and url:
            hits.append(SearchHit(title=title, url=url, snippet=snippet))

    hits = _filter_hits(
        hits,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )
    hits = _dedupe_hits(hits)
    return SearchResponse(
        query=query,
        provider="tavily",
        results=tuple(hits[:count]),
        searched_url=TAVILY_SEARCH_URL,
        truncated=truncated,
        freshness_enforced=bool(freshness and freshness != "any"),
    )


def search_serpapi(
    query: str,
    *,
    allowed_domains: tuple[str, ...] = (),
    blocked_domains: tuple[str, ...] = (),
    count: int = DEFAULT_RESULT_COUNT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> SearchResponse:
    """Search SerpAPI's Google engine and normalize organic results."""

    api_key = get_env_secret("SERPAPI_API_KEY", dotenv_path=".env").strip()
    if not api_key:
        raise WebSearchError("provider_not_configured")

    search_url = (
        f"{SERPAPI_SEARCH_URL}?engine=google"
        f"&q={quote_plus(query)}"
        f"&num={count}"
        f"&api_key={quote_plus(api_key)}"
    )
    request = Request(
        search_url,
        headers={"User-Agent": "KlaraAgentLadder/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read(DEFAULT_SEARCH_MAX_BYTES + 1)
            status = response.getcode()
            final_url = response.geturl()
    except Exception as exc:
        raise WebSearchError(f"serpapi_request_failed: {exc}") from exc

    truncated = len(response_body) > DEFAULT_SEARCH_MAX_BYTES
    response_body = response_body[:DEFAULT_SEARCH_MAX_BYTES]
    try:
        payload = json.loads(response_body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise WebSearchError("serpapi_invalid_json") from exc
    if status is not None and status >= 400:
        raise WebSearchError(f"serpapi_http_{status}")
    if not isinstance(payload, dict):
        raise WebSearchError("serpapi_invalid_payload")
    if error := payload.get("error"):
        raise WebSearchError(f"serpapi_error: {error}")

    raw_results = payload.get("organic_results", [])
    if not isinstance(raw_results, list):
        raise WebSearchError("serpapi_invalid_results")
    hits: list[SearchHit] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("link") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if title and url:
            hits.append(SearchHit(title=title, url=url, snippet=snippet))

    hits = _filter_hits(
        hits,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )
    hits = _dedupe_hits(hits)
    return SearchResponse(
        query=query,
        provider="serpapi",
        results=tuple(hits[:count]),
        searched_url=SERPAPI_SEARCH_URL,
        truncated=truncated,
    )


def parse_duckduckgo_results(html: str) -> list[SearchHit]:
    """Parse DuckDuckGo HTML result anchors.

    Args:
        html: DuckDuckGo HTML response.

    Returns:
        Search hits found in `result__a` anchors.
    """

    anchors = _extract_anchors_with_any_class(
        html,
        required_classes=("result__a", "result-link"),
    )
    snippets = _extract_texts_with_any_class(
        html,
        class_names=("result__snippet", "result-snippet"),
    )
    return _anchors_to_hits(anchors, snippets=snippets)


def parse_generic_links(html: str) -> list[SearchHit]:
    """Parse generic links as a fallback when provider markup changes.

    Args:
        html: HTML response to scan.

    Returns:
        Search hits found in ordinary absolute links.
    """

    anchors = _extract_anchors(html, required_class=None)
    return _anchors_to_hits(anchors, snippets=())


def decode_duckduckgo_redirect(url: str) -> str | None:
    """Decode a DuckDuckGo redirect URL into its original target.

    Args:
        url: Anchor href from a search-result page.

    Returns:
        A public absolute HTTP(S) URL, or None when the href is not web content.
    """

    decoded = unescape(url.strip())
    if decoded.startswith("//"):
        decoded = f"https:{decoded}"
    elif decoded.startswith("/"):
        if not decoded.startswith(("/l?", "/l/", "/l&")):
            return None
        decoded = f"https://duckduckgo.com{decoded}"

    parsed = urlparse(decoded)
    if parsed.scheme not in {"http", "https"}:
        return None

    host = (parsed.hostname or "").lower()
    if host == "duckduckgo.com" or host.endswith(".duckduckgo.com"):
        if parsed.path in {"/l", "/l/"}:
            # Walk query pairs to find the original URL encoded by DuckDuckGo.
            for key, value in parse_qsl(parsed.query, keep_blank_values=True):
                if key == "uddg" and value:
                    return unescape(value)
    return decoded


def _extract_anchors(html: str, *, required_class: str | None) -> list[AnchorCandidate]:
    """Extract anchors from HTML with an optional class filter."""

    parser = AnchorExtractor(required_class=required_class)
    parser.feed(html)
    parser.close()
    return parser.anchors


def _extract_anchors_with_any_class(
    html: str,
    *,
    required_classes: tuple[str, ...],
) -> list[AnchorCandidate]:
    """Extract anchors that match any of several class names."""

    anchors: list[AnchorCandidate] = []
    # Merge per-class parser results while preserving provider rank order.
    for class_name in required_classes:
        anchors.extend(_extract_anchors(html, required_class=class_name))
    return sorted(anchors, key=lambda anchor: html.find(anchor.href))


def _extract_texts_with_any_class(html: str, *, class_names: tuple[str, ...]) -> tuple[str, ...]:
    """Extract text content from elements matching any requested class."""

    parser = ClassTextExtractor(class_names=class_names)
    parser.feed(html)
    parser.close()
    return tuple(parser.texts)


def _anchors_to_hits(
    anchors: list[AnchorCandidate],
    *,
    snippets: tuple[str, ...],
) -> list[SearchHit]:
    """Normalize raw anchors into search hits."""

    hits: list[SearchHit] = []
    # Preserve source order because result ranking comes from the provider page.
    for index, anchor in enumerate(anchors):
        title = " ".join(anchor.text.split())
        if not title:
            continue
        url = decode_duckduckgo_redirect(anchor.href)
        if url is None:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        hits.append(SearchHit(title=title, url=url, snippet=snippet))
    return hits


def _filter_hits(
    hits: list[SearchHit],
    *,
    allowed_domains: tuple[str, ...],
    blocked_domains: tuple[str, ...],
) -> list[SearchHit]:
    """Apply allow and block domain filters to search hits."""

    filtered: list[SearchHit] = []
    # Keep the filter order explicit: allow-list first, block-list second.
    for hit in hits:
        if allowed_domains and not host_matches_domain_list(hit.url, allowed_domains):
            continue
        if blocked_domains and host_matches_domain_list(hit.url, blocked_domains):
            continue
        filtered.append(hit)
    return filtered


def _dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    """Remove duplicate result URLs while preserving order."""

    deduped: list[SearchHit] = []
    seen_urls: set[str] = set()
    # Scan in rank order so the first occurrence wins.
    for hit in hits:
        if hit.url in seen_urls:
            continue
        seen_urls.add(hit.url)
        deduped.append(hit)
    return deduped


def _provider_order() -> tuple[str, ...]:
    """Return configured search providers in fallback order."""

    raw = get_env_secret("WEB_SEARCH_PROVIDER_ORDER", dotenv_path=".env").strip()
    if not raw:
        return DEFAULT_PROVIDER_ORDER
    providers = tuple(
        provider.strip().lower()
        for provider in raw.split(",")
        if provider.strip()
    )
    return providers or DEFAULT_PROVIDER_ORDER


def _failure_type(error: str) -> str:
    """Classify provider failures for model-visible recovery."""

    lowered = error.lower()
    if "anti_bot_challenge" in lowered or "challenge" in lowered:
        return "anti_bot_challenge"
    if "provider_not_configured" in lowered:
        return "provider_not_configured"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "http 429" in lowered or "rate" in lowered:
        return "rate_limited"
    if "http" in lowered:
        return "http_error"
    if "network" in lowered or "urlopen" in lowered:
        return "network_error"
    return "provider_error"


def _looks_like_challenge_page(html: str) -> bool:
    """Return whether the provider response is an anti-automation page."""

    lowered = html.lower()
    return "anomaly-modal" in lowered or "data-testid=\"anomaly" in lowered
