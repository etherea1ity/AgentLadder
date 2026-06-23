"""Model-visible web search capability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Callable
from urllib.parse import urlparse, urlunparse

from klara.tools.base import BaseTool, ToolInputError
from klara.tools.builtin.web_search.schema import WEB_SEARCH_METADATA, WEB_SEARCH_SPEC
from klara.core.tools import JsonObject, ToolMetadata, ToolResult, ToolSpec
from klara.services.web import SearchResponse, WebSearchError, search_web


Searcher = Callable[..., SearchResponse]


@dataclass(frozen=True)
class WebSearchTool(BaseTool):
    """Search the public web and return URLs for later fetching.

    This tool owns the schema and runtime metadata. Provider-specific search
    behavior stays in `klara.services.web` so later official providers can be
    added without changing core loop mechanics.
    """

    spec: ToolSpec = WEB_SEARCH_SPEC
    metadata: ToolMetadata = WEB_SEARCH_METADATA
    searcher: Searcher = search_web

    def run(self, arguments: JsonObject) -> ToolResult:
        """Run a public web search and return structured results.

        Args:
            arguments: JSON-like arguments with `query` and optional filters.

        Returns:
            A JSON observation with ranked search results, or a failed
            observation when the provider cannot be reached.
        """

        query = self.optional_string(arguments, "query")
        if not query:
            raise ToolInputError("query must not be empty")
        allowed_domains = _optional_string_tuple(arguments, "allowed_domains")
        blocked_domains = _optional_string_tuple(arguments, "blocked_domains")
        count = _optional_int(arguments, "count", default=8)
        if count < 1 or count > 20:
            raise ToolInputError("count must be between 1 and 20")
        freshness = _optional_freshness(arguments)
        date_after = _optional_iso_date(arguments, "date_after")
        date_before = _optional_iso_date(arguments, "date_before")
        language = _optional_language(arguments)
        country = _optional_compact_hint(arguments, "country")
        search_depth = _optional_search_depth(arguments)
        require_freshness_enforced = _optional_bool(arguments, "require_freshness_enforced")
        search_hints = _search_hints(
            freshness=freshness,
            date_after=date_after,
            date_before=date_before,
            language=language,
            country=country,
            search_depth=search_depth,
        )
        if require_freshness_enforced:
            raise ToolInputError(
                "configured web_search provider cannot enforce freshness hints"
            )
        effective_query = _apply_search_hints(query, search_hints)

        try:
            response = self.searcher(
                effective_query,
                allowed_domains=allowed_domains,
                blocked_domains=blocked_domains,
                count=count,
                timeout_seconds=self.metadata.timeout_seconds,
            )
        except WebSearchError as exc:
            return self.failure(arguments, str(exc))
        searched_at = datetime.now(UTC).isoformat(timespec="seconds")
        search_id = _stable_id("search", response.provider, response.query, searched_at)
        results = _result_cards(response, search_id=search_id)[:count]

        return self.json_success(
            arguments,
            {
                "observation_kind": "web_search_candidates",
                "evidence_status": "candidate_snippets_only",
                "search_id": search_id,
                "query": response.query,
                "original_query": query,
                "effective_query": effective_query,
                "search_hints": search_hints,
                "provider_limitations": (
                    "The no-key search provider may not enforce freshness or "
                    "language hints. Treat snippets as candidates and verify "
                    "time-sensitive facts with fetched source text."
                ),
                "provider": response.provider,
                "freshness_enforced": False,
                "result_count": len(results),
                "results": results,
                "searched_url": response.searched_url,
                "truncated": response.truncated,
                "searched_at": searched_at,
                "trust": "untrusted_external_content",
            },
        )


def _optional_string_tuple(arguments: JsonObject, key: str) -> tuple[str, ...]:
    """Read an optional list of non-empty strings."""

    value = arguments.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ToolInputError(f"{key} must be an array of strings")
    strings: list[str] = []
    # Validate each domain entry so provider filters stay deterministic.
    for item in value:
        if not isinstance(item, str):
            raise ToolInputError(f"{key} must be an array of strings")
        text = item.strip()
        if text:
            strings.append(text)
    return tuple(strings)


def _optional_int(arguments: JsonObject, key: str, *, default: int) -> int:
    """Read an optional integer argument."""

    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{key} must be an integer")
    return value


def _optional_freshness(arguments: JsonObject) -> str:
    """Read an optional freshness hint supported by the tool schema."""

    value = arguments.get("freshness")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ToolInputError("freshness must be a string")
    freshness = value.strip().lower()
    if not freshness:
        return ""
    if freshness not in {"day", "week", "month", "year", "any"}:
        raise ToolInputError("freshness must be day, week, month, year, or any")
    return freshness


def _optional_iso_date(arguments: JsonObject, key: str) -> str:
    """Read an optional YYYY-MM-DD date hint."""

    value = arguments.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ToolInputError(f"{key} must be a string")
    text = value.strip()
    if not text:
        return ""
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ToolInputError(f"{key} must use YYYY-MM-DD") from exc
    return text


def _optional_language(arguments: JsonObject) -> str:
    """Read an optional compact language hint."""

    return _optional_compact_hint(arguments, "language")


def _optional_compact_hint(arguments: JsonObject, key: str) -> str:
    """Read an optional compact provider hint."""

    value = arguments.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ToolInputError(f"{key} must be a string")
    hint = value.strip().lower()
    if not hint:
        return ""
    if len(hint) > 24 or not all(
        char.isascii() and (char.isalnum() or char in {"-", "_"})
        for char in hint
    ):
        raise ToolInputError(f"{key} must be a compact ISO-style hint")
    return hint


def _optional_search_depth(arguments: JsonObject) -> str:
    """Read an optional search depth hint."""

    value = arguments.get("search_depth")
    if value is None:
        return "basic"
    if not isinstance(value, str):
        raise ToolInputError("search_depth must be a string")
    depth = value.strip().lower()
    if depth not in {"basic", "advanced"}:
        raise ToolInputError("search_depth must be basic or advanced")
    return depth


def _optional_bool(arguments: JsonObject, key: str) -> bool:
    """Read an optional boolean argument."""

    value = arguments.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ToolInputError(f"{key} must be a boolean")
    return value


def _search_hints(
    *,
    freshness: str,
    date_after: str,
    date_before: str,
    language: str,
    country: str,
    search_depth: str,
) -> dict[str, str]:
    """Return only caller-provided search hints for transparent observations."""

    hints: dict[str, str] = {}
    if freshness:
        hints["freshness"] = freshness
    if date_after:
        hints["date_after"] = date_after
    if date_before:
        hints["date_before"] = date_before
    if language:
        hints["language"] = language
    if country:
        hints["country"] = country
    if search_depth and search_depth != "basic":
        hints["search_depth"] = search_depth
    return hints


def _apply_search_hints(query: str, search_hints: dict[str, str]) -> str:
    """Fold portable search hints into the query for no-key providers."""

    extras: list[str] = []
    # Freshness and language are reported in the observation, but DuckDuckGo
    # Lite does not give us a stable no-key way to enforce them. Appending
    # phrases such as "past day" or "language:zh" pollutes some real queries.
    if date_after := search_hints.get("date_after"):
        extras.append(f"after:{date_after}")
    if date_before := search_hints.get("date_before"):
        extras.append(f"before:{date_before}")
    if not extras:
        return query
    return " ".join([query, *extras])


def _result_cards(response: SearchResponse, *, search_id: str) -> list[dict[str, object]]:
    """Return search cards in provider order."""

    cards: list[dict[str, object]] = []
    for original_rank, hit in enumerate(response.results, start=1):
        canonical_url = _canonical_url(hit.url)
        cards.append(
            {
                "candidate_id": _stable_id("cand", search_id, str(original_rank), canonical_url),
                "title": hit.title,
                "url": hit.url,
                "canonical_url": canonical_url,
                "snippet": hit.snippet,
                "rank": original_rank,
                "original_rank": original_rank,
                "published_at": None,
                "source_type": "unknown",
                "must_fetch_before_citing": True,
            }
        )
    return cards


def _canonical_url(url: str) -> str:
    """Return a stable URL form for evidence joins."""

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    netloc = hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def _stable_id(prefix: str, *parts: str) -> str:
    """Return a compact deterministic id from public fields."""

    digest = sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"
