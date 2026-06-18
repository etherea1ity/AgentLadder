"""Timezone helpers for the current-time tool."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_FIXED_TIMEZONES: dict[str, tzinfo] = {
    "UTC": timezone.utc,
    "Asia/Shanghai": timezone(timedelta(hours=8), name="Asia/Shanghai"),
}


def resolve_timezone(timezone_name: str) -> tuple[str, tzinfo]:
    """Resolve a user-requested timezone into a Python timezone object.

    Args:
        timezone_name: Empty, local, fixed, or IANA timezone name.

    Returns:
        A display name and a timezone object suitable for `datetime.now`.

    Raises:
        ValueError: If the requested timezone cannot be resolved.
    """

    if not timezone_name or timezone_name.lower() == "local":
        return "local", datetime.now().astimezone().tzinfo or timezone.utc
    if timezone_name in _FIXED_TIMEZONES:
        return timezone_name, _FIXED_TIMEZONES[timezone_name]
    try:
        return timezone_name, ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc


def format_utc_offset(value: datetime) -> str:
    """Return an ISO-like UTC offset for a timezone-aware datetime.

    Args:
        value: Timezone-aware datetime value.

    Returns:
        Offset text such as `+08:00`.
    """

    offset = value.utcoffset()
    if offset is None:
        return "+00:00"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    abs_minutes = abs(total_minutes)
    hours, minutes = divmod(abs_minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"
