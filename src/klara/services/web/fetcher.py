"""Public web page fetching service used by web tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl
from urllib.request import HTTPRedirectHandler, Request, build_opener

from klara.services.web.html_text import collapse_whitespace, html_to_text
from klara.services.web.safety import WebSafetyError, validate_public_http_url


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_BYTES = 300_000
DEFAULT_MAX_CHARS = 4_000
USER_AGENT = "KlaraAgentLadder/0.1 (+https://local.agentladder)"


class WebFetchError(RuntimeError):
    """Raised when a page cannot be fetched for a model-visible observation."""


@dataclass(frozen=True)
class HttpDocument:
    """Raw HTTP response text returned by the guarded reader."""

    url: str
    final_url: str
    status: int | None
    content_type: str
    text: str
    truncated: bool


@dataclass(frozen=True)
class FetchedPage:
    """Readable page content prepared for a web-fetch tool observation."""

    url: str
    final_url: str
    status: int | None
    content_type: str
    title: str
    text: str
    truncated: bool


class ResponseLike(Protocol):
    """Subset of urllib response behavior used by the fetch service."""

    headers: object

    def read(self, amt: int | None = None) -> bytes:
        """Read bytes from the response body."""

    def geturl(self) -> str:
        """Return the final response URL."""

    def getcode(self) -> int | None:
        """Return the HTTP status code."""


OpenRequest = Callable[[Request, float], ResponseLike]
ReadHttpText = Callable[..., HttpDocument]


class SafeRedirectHandler(HTTPRedirectHandler):
    """Validate redirect targets before urllib follows them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        """Reject redirects to local or non-public hosts."""

        validate_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = build_opener(SafeRedirectHandler)


def read_http_text(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    opener: OpenRequest | None = None,
) -> HttpDocument:
    """Fetch a public HTTP(S) URL and decode a bounded text response.

    Args:
        url: Public HTTP(S) URL to request.
        timeout_seconds: Network timeout for this request.
        max_bytes: Maximum response bytes to expose to decoding.
        opener: Optional test seam that mimics `urllib` opening a request.

    Returns:
        Raw decoded HTTP response text plus response metadata.

    Raises:
        WebFetchError: If validation, transport, or decoding fails.
    """

    if timeout_seconds <= 0:
        raise WebFetchError("timeout_seconds must be positive")
    if max_bytes < 1:
        raise WebFetchError("max_bytes must be positive")

    try:
        safe_url = validate_public_http_url(url)
        request = Request(safe_url, headers={"User-Agent": USER_AGENT})
        response = (opener or _open_request)(request, timeout_seconds)
        body = response.read(max_bytes + 1)
    except WebSafetyError as exc:
        raise WebFetchError(str(exc)) from exc
    except HTTPError as exc:
        raise WebFetchError(f"HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise WebFetchError(f"Network error: {exc.reason}") from exc
    except OSError as exc:
        raise WebFetchError(f"Network error: {exc}") from exc

    if isinstance(body, str):
        raw_bytes = body.encode("utf-8")
    else:
        raw_bytes = body
    is_byte_truncated = len(raw_bytes) > max_bytes
    raw_bytes = raw_bytes[:max_bytes]

    content_type = _content_type(response.headers)
    charset = _charset(response.headers) or "utf-8"
    text = raw_bytes.decode(charset, errors="replace")

    return HttpDocument(
        url=safe_url,
        final_url=response.geturl(),
        status=response.getcode(),
        content_type=content_type,
        text=text,
        truncated=is_byte_truncated,
    )


def fetch_page(
    url: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    reader: ReadHttpText = read_http_text,
) -> FetchedPage:
    """Fetch a page and return readable, bounded text.

    Args:
        url: Public HTTP(S) URL to fetch.
        max_chars: Maximum characters to return in `FetchedPage.text`.
        timeout_seconds: Network timeout passed to the HTTP reader.
        reader: Optional test seam for supplying raw HTTP text.

    Returns:
        A readable page observation.

    Raises:
        WebFetchError: If fetching or response normalization fails.
    """

    if max_chars < 1:
        raise WebFetchError("max_chars must be positive")

    document = reader(url, timeout_seconds=timeout_seconds)
    if "html" in document.content_type:
        title, readable_text = html_to_text(document.text)
    else:
        title = ""
        readable_text = collapse_whitespace(document.text)

    limited_text, is_text_truncated = limit_text(readable_text, max_chars=max_chars)
    return FetchedPage(
        url=document.url,
        final_url=document.final_url,
        status=document.status,
        content_type=document.content_type,
        title=title,
        text=limited_text,
        truncated=document.truncated or is_text_truncated,
    )


def limit_text(text: str, *, max_chars: int) -> tuple[str, bool]:
    """Limit text by character count.

    Args:
        text: Text to limit.
        max_chars: Maximum returned characters.

    Returns:
        A `(limited_text, is_truncated)` pair.
    """

    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip(), True


def _open_request(request: Request, timeout_seconds: float) -> ResponseLike:
    """Open a request through the guarded urllib opener."""

    return _OPENER.open(request, timeout=timeout_seconds)


def _content_type(headers: object) -> str:
    """Return a normalized content type from response headers."""

    if hasattr(headers, "get_content_type"):
        content_type = headers.get_content_type()  # type: ignore[attr-defined]
        if content_type:
            return str(content_type).lower()
    if hasattr(headers, "get"):
        raw = headers.get("Content-Type", "")  # type: ignore[attr-defined]
        return str(raw).split(";", 1)[0].strip().lower() or "text/plain"
    return "text/plain"


def _charset(headers: object) -> str | None:
    """Return a declared response charset when one is available."""

    if hasattr(headers, "get_content_charset"):
        charset = headers.get_content_charset()  # type: ignore[attr-defined]
        if charset:
            return str(charset)
    if not hasattr(headers, "get"):
        return None
    raw = str(headers.get("Content-Type", ""))  # type: ignore[attr-defined]
    # Walk content-type parameters so charset lookup works without email.Message.
    for key, value in parse_qsl(raw.replace(";", "&"), keep_blank_values=True):
        if key.strip().lower() == "charset" and value.strip():
            return value.strip()
    return None

