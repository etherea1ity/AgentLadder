from __future__ import annotations

import pytest

from klara.services.web.fetcher import HttpDocument, fetch_page
from klara.services.web.safety import WebSafetyError, validate_public_http_url


def test_fetch_page_extracts_title_and_readable_html_text() -> None:
    """HTML pages should become compact model-visible text."""

    def reader(url: str, *, timeout_seconds: float) -> HttpDocument:
        return HttpDocument(
            url=url,
            final_url=url,
            status=200,
            content_type="text/html",
            text="""
            <html>
              <head><title>Example Page</title><script>ignore()</script></head>
              <body><h1>Hello</h1><p>Readable web text.</p></body>
            </html>
            """,
            truncated=False,
        )

    page = fetch_page("https://example.com/page", max_chars=200, reader=reader)

    assert page.title == "Example Page"
    assert "Hello" in page.text
    assert "Readable web text." in page.text
    assert "ignore()" not in page.text
    assert page.truncated is False


def test_fetch_page_limits_plain_text() -> None:
    """Fetch service should bound text before tools expose it to the model."""

    def reader(url: str, *, timeout_seconds: float) -> HttpDocument:
        return HttpDocument(
            url=url,
            final_url=url,
            status=200,
            content_type="text/plain",
            text="abcdefghij",
            truncated=False,
        )

    page = fetch_page("https://example.com/plain", max_chars=4, reader=reader)

    assert page.text == "abcd"
    assert page.truncated is True


def test_validate_public_http_url_rejects_local_addresses() -> None:
    """The web reader should not be usable as a localhost/private-network tunnel."""

    with pytest.raises(WebSafetyError, match="Localhost"):
        validate_public_http_url("http://localhost:8000")

    with pytest.raises(WebSafetyError, match="public IP"):
        validate_public_http_url("http://127.0.0.1:8000")

