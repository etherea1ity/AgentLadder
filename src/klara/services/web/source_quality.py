"""Source quality labels for web evidence ranking."""

from __future__ import annotations

from urllib.parse import urlparse


PREFERRED_CURRENT_SPORTS_QUALITIES = {"official", "wire", "sports_media"}

_AGGREGATOR_DOMAINS = {
    "fifawatch.com",
    "worldcupper.com",
    "fifaworldcupnews.com",
    "fwclive.com",
    "2026fifa.tw",
    "cupindex.com",
}


def classify_source(url: str, title: str = "") -> str:
    """Classify a public source by broad evidence quality."""

    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    path = urlparse(url).path.lower()
    lowered_title = title.lower()

    if _host_matches(host, "fifa.com"):
        return "official"
    if _host_matches(host, "reuters.com") or _host_matches(host, "apnews.com"):
        return "wire"
    if _host_matches(host, "espn.com") or _host_matches(host, "foxsports.com"):
        return "sports_media"
    if _host_matches(host, "bbc.com") and path.startswith("/sport"):
        return "sports_media"
    if _host_matches(host, "bbc.co.uk") and path.startswith("/sport"):
        return "sports_media"
    if _host_matches(host, "theguardian.com") and (
        path.startswith("/football") or "football" in lowered_title
    ):
        return "sports_media"
    if any(_host_matches(host, domain) for domain in _AGGREGATOR_DOMAINS):
        return "aggregator"
    return "unknown"


def is_preferred_for_current_sports(source_quality: str) -> bool:
    """Return whether a source quality is preferred for current sports facts."""

    return source_quality in PREFERRED_CURRENT_SPORTS_QUALITIES


def source_quality_rank(source_quality: str) -> int:
    """Return a stable sort rank for current-sports evidence."""

    return {
        "official": 0,
        "wire": 1,
        "sports_media": 1,
        "unknown": 2,
        "aggregator": 3,
    }.get(source_quality, 2)


def _host_matches(host: str, domain: str) -> bool:
    """Return whether host is a domain or one of its subdomains."""

    return host == domain or host.endswith(f".{domain}")
