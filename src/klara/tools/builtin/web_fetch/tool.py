"""Model-visible web page fetch capability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Callable

from klara.tools.base import BaseTool, ToolInputError
from klara.tools.builtin.web_fetch.schema import WEB_FETCH_METADATA, WEB_FETCH_SPEC
from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec
from klara.services.web import FetchedPage, WebFetchError, fetch_page


PageFetcher = Callable[..., FetchedPage]


@dataclass(frozen=True)
class WebFetchTool(BaseTool):
    """Fetch readable text from one public web page.

    This tool owns the model-facing contract and wraps the web service boundary.
    It does not decide provider policy, loop behavior, or frontend projection.
    """

    spec: ToolSpec = WEB_FETCH_SPEC
    metadata: ToolMetadata = WEB_FETCH_METADATA
    page_fetcher: PageFetcher = fetch_page

    def run(self, arguments: JsonObject) -> ToolResult:
        """Fetch one public page and return a structured observation.

        Args:
            arguments: JSON-like arguments with `url` and optional `max_chars`.

        Returns:
            A JSON observation with readable page text, or a failed observation
            when the URL cannot be fetched safely.
        """

        url = self.optional_string(arguments, "url")
        if not url:
            raise ToolInputError("url must not be empty")
        candidate_id = self.optional_string(arguments, "candidate_id") or None
        requested_source_id = self.optional_string(arguments, "source_id") or None
        max_chars = _optional_int(arguments, "max_chars", default=4000)
        if max_chars < 200 or max_chars > 12000:
            raise ToolInputError("max_chars must be between 200 and 12000")
        query_terms = _optional_string_list(arguments, "query_terms")
        extract_mode = _optional_extract_mode(arguments)

        try:
            page = self.page_fetcher(
                url,
                max_chars=max_chars,
                timeout_seconds=self.metadata.timeout_seconds,
            )
        except WebFetchError as exc:
            return self.failure(arguments, str(exc))
        text, no_relevant_terms_found = _extract_text(
            page.text,
            query_terms=query_terms,
            extract_mode=extract_mode,
            max_chars=max_chars,
        )
        quality = _extraction_quality(
            page=page,
            text=text,
            query_terms=query_terms,
            no_relevant_terms_found=no_relevant_terms_found,
        )
        source_id = requested_source_id or _stable_id("src", page.final_url or page.url)

        return self.json_success(
            arguments,
            {
                "observation_kind": "web_fetched_source",
                "source_id": source_id,
                "candidate_id": candidate_id,
                "url": page.url,
                "final_url": page.final_url,
                "status": page.status,
                "content_type": page.content_type,
                "title": page.title,
                "text": text,
                "text_length": len(text),
                "truncated": page.truncated,
                "extract_mode": extract_mode,
                "query_terms": query_terms,
                "no_relevant_terms_found": no_relevant_terms_found,
                "extraction_quality": quality,
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "trust": "untrusted_external_content",
            },
        )


def _optional_int(arguments: JsonObject, key: str, *, default: int) -> int:
    """Read an optional integer argument."""

    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{key} must be an integer")
    return value


def _optional_string_list(arguments: JsonObject, key: str) -> list[str]:
    """Read an optional list of non-empty strings."""

    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolInputError(f"{key} must be an array of strings")
    terms: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ToolInputError(f"{key} must be an array of strings")
        text = " ".join(item.split())
        if text:
            terms.append(text)
    return terms[:16]


def _optional_extract_mode(arguments: JsonObject) -> str:
    """Read the optional extraction mode."""

    value = arguments.get("extract_mode")
    if value is None:
        return "plain"
    if not isinstance(value, str):
        raise ToolInputError("extract_mode must be a string")
    mode = value.strip()
    if mode not in {"plain", "relevant_snippets", "summary_snippets"}:
        raise ToolInputError(
            "extract_mode must be plain, relevant_snippets, or summary_snippets"
        )
    if mode == "summary_snippets":
        return "relevant_snippets"
    return mode


def _extract_text(
    text: str,
    *,
    query_terms: list[str],
    extract_mode: str,
    max_chars: int,
) -> tuple[str, bool]:
    """Return plain text or term-centered snippets."""

    if extract_mode != "relevant_snippets":
        return text, False
    snippets = _relevant_snippets(text, query_terms=query_terms, max_chars=max_chars)
    if snippets:
        return snippets, False
    return text[:max_chars].rstrip(), True


def _relevant_snippets(text: str, *, query_terms: list[str], max_chars: int) -> str:
    """Extract compact windows around requested query terms."""

    if not query_terms:
        return ""
    lowered = text.lower()
    windows: list[tuple[int, int]] = []
    window_radius = max(220, min(700, max_chars // 4))
    for term in query_terms:
        index = lowered.find(term.lower())
        if index < 0:
            continue
        windows.append((max(0, index - window_radius), min(len(text), index + len(term) + window_radius)))
    if not windows:
        return ""
    merged = _merge_windows(sorted(windows))
    parts = [" ".join(text[start:end].split()) for start, end in merged]
    return "\n\n---\n\n".join(part for part in parts if part)[:max_chars].rstrip()


def _merge_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping snippet windows."""

    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if not merged or start > merged[-1][1] + 40:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _extraction_quality(
    *,
    page: FetchedPage,
    text: str,
    query_terms: list[str],
    no_relevant_terms_found: bool,
) -> dict[str, object]:
    """Score generic readable-text quality for research readiness."""

    text_length = len(text)
    looks_like_js_shell = _looks_like_js_shell(text)
    has_title = bool(page.title.strip())
    has_relevant_terms = bool(query_terms) and not no_relevant_terms_found
    score = 0.0
    if page.status is not None and 200 <= page.status < 300:
        score += 0.25
    if has_title:
        score += 0.15
    if text_length >= 1200:
        score += 0.35
    elif text_length >= 400:
        score += 0.22
    elif text_length >= 120:
        score += 0.08
    if query_terms:
        score += 0.2 if has_relevant_terms else -0.15
    else:
        score += 0.05
    if looks_like_js_shell:
        score -= 0.3
    score = max(0.0, min(1.0, round(score, 2)))
    return {
        "score": score,
        "looks_like_js_shell": looks_like_js_shell,
        "has_title": has_title,
        "has_relevant_terms": has_relevant_terms,
        "text_length": text_length,
    }


def _looks_like_js_shell(text: str) -> bool:
    """Return whether readable text looks like a navigation or JS shell."""

    compact = " ".join(text.lower().split())
    if len(compact) < 160:
        return True
    shell_markers = (
        "enable javascript",
        "please enable javascript",
        "app shell",
        "navigation",
        "login",
        "cookie",
    )
    return any(marker in compact for marker in shell_markers) and len(compact) < 600


def _stable_id(prefix: str, *parts: str) -> str:
    """Return a compact deterministic id from public source fields."""

    digest = sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"

