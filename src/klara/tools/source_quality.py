"""Shared source-quality labels for web-facing tools."""

from __future__ import annotations

from urllib.parse import urlparse


PREFERRED_SOURCE_DOMAINS = (
    "fifa.com",
    "espn.com",
    "bbc.com",
    "cctv.cn",
    "reuters.com",
    "apnews.com",
    "theguardian.com",
    "cbssports.com",
    "foxsports.com",
    "skysports.com",
)


def source_tier(url: str) -> str:
    """Return a coarse model-visible source-quality label."""

    hostname = (urlparse(url).hostname or "").lower()
    if any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in PREFERRED_SOURCE_DOMAINS
    ):
        return "preferred_source"
    return "candidate_source"
