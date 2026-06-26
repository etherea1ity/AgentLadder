from __future__ import annotations

import json

from klara.services.web.fetcher import HttpDocument
from klara.services.web.search import search_web


def test_search_web_decodes_duckduckgo_redirects_and_filters_domains() -> None:
    """DuckDuckGo HTML results should normalize redirect URLs and domain filters."""

    html = """
    <html><body>
      <a class="result-link" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F&amp;rut=abc">
        Python docs
      </a>
      <td class="result-snippet">Official Python documentation.</td>
      <a class="result__a" href="https://example.com/blocked">Blocked result</a>
    </body></html>
    """

    def reader(url: str, *, timeout_seconds: float, max_bytes: int) -> HttpDocument:
        return HttpDocument(
            url=url,
            final_url=url,
            status=200,
            content_type="text/html",
            text=html,
            truncated=False,
        )

    response = search_web(
        "python docs",
        allowed_domains=("python.org",),
        count=8,
        reader=reader,
    )

    assert response.provider == "duckduckgo_lite"
    assert [hit.title for hit in response.results] == ["Python docs"]
    assert response.results[0].url == "https://docs.python.org/3/"
    assert response.results[0].snippet == "Official Python documentation."


def test_search_web_falls_back_to_generic_absolute_links() -> None:
    """Generic link parsing keeps the no-key search tool resilient to markup changes."""

    html = """
    <html><body>
      <a href="/relative">Relative</a>
      <a href="https://example.com/a">Example A</a>
      <a href="https://example.com/a">Example A Duplicate</a>
      <a href="https://blocked.example/a">Blocked</a>
    </body></html>
    """

    def reader(url: str, *, timeout_seconds: float, max_bytes: int) -> HttpDocument:
        return HttpDocument(
            url=url,
            final_url=url,
            status=200,
            content_type="text/html",
            text=html,
            truncated=False,
        )

    response = search_web(
        "fallback",
        blocked_domains=("blocked.example",),
        count=8,
        reader=reader,
    )

    assert [(hit.title, hit.url) for hit in response.results] == [
        ("Example A", "https://example.com/a")
    ]


def test_search_web_falls_back_from_duckduckgo_challenge_to_tavily(monkeypatch) -> None:
    """Provider fallback should recover when DuckDuckGo returns a challenge page."""

    monkeypatch.setenv("WEB_SEARCH_PROVIDER_ORDER", "duckduckgo_lite,tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    def reader(url: str, *, timeout_seconds: float, max_bytes: int) -> HttpDocument:
        return HttpDocument(
            url=url,
            final_url=url,
            status=200,
            content_type="text/html",
            text='<div data-testid="anomaly-modal">Challenge</div>',
            truncated=False,
        )

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

        def read(self, amount: int) -> bytes:
            payload = {
                "results": [
                    {
                        "title": "Current news",
                        "url": "https://example.com/news",
                        "content": "A current news result.",
                    }
                ]
            }
            return json.dumps(payload).encode("utf-8")

        def getcode(self) -> int:
            return 200

    def fake_urlopen(request, timeout: float) -> FakeResponse:  # type: ignore[no-untyped-def]
        return FakeResponse()

    monkeypatch.setattr("klara.services.web.search.urlopen", fake_urlopen)

    response = search_web("current news", count=3, reader=reader)

    assert response.provider == "tavily"
    assert response.results[0].title == "Current news"
    assert response.provider_attempts == (
        {
            "provider": "duckduckgo_lite",
            "ok": False,
            "failure_type": "anti_bot_challenge",
            "error": "anti_bot_challenge",
        },
        {"provider": "tavily", "ok": True},
    )


def test_search_web_can_use_serpapi_provider(monkeypatch) -> None:
    """SerpAPI should be available as a configured fallback provider."""

    monkeypatch.setenv("WEB_SEARCH_PROVIDER_ORDER", "serpapi")
    monkeypatch.setenv("SERPAPI_API_KEY", "test-serpapi-key")

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

        def read(self, amount: int) -> bytes:
            payload = {
                "organic_results": [
                    {
                        "title": "Serp result",
                        "link": "https://example.org/result",
                        "snippet": "A normalized SerpAPI result.",
                    }
                ]
            }
            return json.dumps(payload).encode("utf-8")

        def getcode(self) -> int:
            return 200

        def geturl(self) -> str:
            return "https://serpapi.com/search.json?api_key=test-serpapi-key"

    def fake_urlopen(request, timeout: float) -> FakeResponse:  # type: ignore[no-untyped-def]
        return FakeResponse()

    monkeypatch.setattr("klara.services.web.search.urlopen", fake_urlopen)

    response = search_web("serp query", count=2)

    assert response.provider == "serpapi"
    assert response.searched_url == "https://serpapi.com/search.json"
    assert response.results[0].title == "Serp result"
    assert response.provider_attempts == ({"provider": "serpapi", "ok": True},)
