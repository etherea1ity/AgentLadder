"""Small HTML-to-text extraction helpers for web fetch observations."""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser


BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas"}


class HtmlTextExtractor(HTMLParser):
    """Extract readable page text and title from HTML.

    The extractor is intentionally small. It does not own network access,
    markdown conversion, readability scoring, or summarization.
    """

    def __init__(self) -> None:
        """Create an empty HTML text extractor."""

        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._skip_depth = 0
        self._is_title = False

    @property
    def title(self) -> str:
        """Return the extracted document title."""

        return collapse_whitespace(" ".join(self._title_parts))

    @property
    def text(self) -> str:
        """Return readable body text with compact whitespace."""

        return collapse_whitespace("".join(self._parts))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track block, title, and skipped elements while parsing."""

        tag_name = tag.lower()
        if tag_name in SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag_name == "title":
            self._is_title = True
            return
        if tag_name in BLOCK_TAGS:
            self._append_break()

    def handle_endtag(self, tag: str) -> None:
        """Close parser state for block, title, and skipped elements."""

        tag_name = tag.lower()
        if tag_name in SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag_name == "title":
            self._is_title = False
            return
        if tag_name in BLOCK_TAGS:
            self._append_break()

    def handle_data(self, data: str) -> None:
        """Collect visible text data from the current parser position."""

        if self._is_title:
            self._title_parts.append(data)
            return
        if self._skip_depth > 0:
            return
        self._parts.append(data)

    def _append_break(self) -> None:
        """Append a paragraph break when the last part is not already one."""

        if not self._parts or self._parts[-1].endswith("\n"):
            return
        self._parts.append("\n")


def html_to_text(html: str) -> tuple[str, str]:
    """Extract title and readable text from HTML.

    Args:
        html: Raw HTML string.

    Returns:
        A `(title, text)` pair. Either value may be empty.
    """

    extractor = HtmlTextExtractor()
    extractor.feed(html)
    extractor.close()
    return extractor.title, extractor.text


def collapse_whitespace(text: str) -> str:
    """Collapse repeated whitespace while preserving paragraph breaks.

    Args:
        text: Raw text to compact.

    Returns:
        Text with compact lines and blank lines removed.
    """

    lines: list[str] = []
    # Normalize each line independently so paragraph boundaries remain visible.
    for line in unescape(text).splitlines():
        compact = " ".join(line.split())
        if compact:
            lines.append(compact)
    return "\n".join(lines).strip()

