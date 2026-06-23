"""URL validation for public web access tools."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse, urlunparse


class WebSafetyError(ValueError):
    """Raised when a requested web URL is outside the public web boundary."""


_BENCHMARK_PROXY_NETWORKS = (
    ipaddress.ip_network("198.18.0.0/15"),
)


def validate_public_http_url(raw_url: str) -> str:
    """Validate and normalize a public HTTP(S) URL.

    Args:
        raw_url: User or model supplied URL.

    Returns:
        A normalized URL string that is safe to request.

    Raises:
        WebSafetyError: If the URL is malformed, unsupported, or resolves to a
            non-public host.
    """

    text = raw_url.strip()
    if not text:
        raise WebSafetyError("URL must not be empty")

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise WebSafetyError("URL must use http or https")
    if not parsed.hostname:
        raise WebSafetyError("URL must include a host")
    if parsed.username or parsed.password:
        raise WebSafetyError("URL must not include credentials")

    host = parsed.hostname.strip().lower()
    _reject_local_hostname(host)
    _reject_private_addresses(host)

    normalized = parsed._replace(fragment="")
    return urlunparse(normalized)


def host_matches_domain_list(url: str, domains: tuple[str, ...]) -> bool:
    """Return whether a URL host matches at least one configured domain.

    Args:
        url: Absolute URL to inspect.
        domains: Lowercase or mixed-case domain filters.

    Returns:
        True when the URL host is equal to, or a subdomain of, one filter.
    """

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    normalized_host = host.lower().strip(".")
    normalized_domains = tuple(_normalize_domain(domain) for domain in domains)

    # Scan each configured domain so callers can express coarse allow/block sets.
    for domain in normalized_domains:
        if not domain:
            continue
        if normalized_host == domain or normalized_host.endswith(f".{domain}"):
            return True
    return False


def _reject_local_hostname(host: str) -> None:
    """Reject hostnames that always refer to local machine resources."""

    if host in {"localhost", "localhost.localdomain"}:
        raise WebSafetyError("Localhost URLs are not allowed")
    if host.endswith(".localhost"):
        raise WebSafetyError("Localhost URLs are not allowed")


def _reject_private_addresses(host: str) -> None:
    """Reject literal or resolved non-public IP addresses."""

    try:
        literal_address = ipaddress.ip_address(host)
    except ValueError:
        literal_address = None
    if literal_address is not None:
        _reject_if_not_public_ip(literal_address, allow_benchmark_proxy=False)
        return

    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise WebSafetyError(f"Could not resolve host: {host}") from exc

    # Inspect every resolved address because a single private answer is enough
    # to make the request unsafe for this teaching runtime.
    for address in addresses:
        sockaddr = address[4]
        ip_text = str(sockaddr[0])
        _reject_if_not_public_ip(ipaddress.ip_address(ip_text), allow_benchmark_proxy=True)


def _reject_if_not_public_ip(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_benchmark_proxy: bool,
) -> None:
    """Reject IP ranges that should not be reachable through public web tools."""

    if not address.is_global:
        if allow_benchmark_proxy and _is_benchmark_proxy_address(address):
            return
        raise WebSafetyError("URL host must resolve to a public IP address")


def _is_benchmark_proxy_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return whether DNS points through a local external-web proxy range."""

    return any(address in network for network in _BENCHMARK_PROXY_NETWORKS)


def _normalize_domain(domain: str) -> str:
    """Normalize a caller-provided domain filter."""

    text = domain.strip().lower()
    if "://" in text:
        parsed = urlparse(text)
        text = parsed.hostname or ""
    return text.strip(".")

