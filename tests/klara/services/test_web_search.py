from __future__ import annotations

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
