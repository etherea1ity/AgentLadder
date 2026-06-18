"""Prompt-facing timestamp helpers for model-visible user messages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIMESTAMP_PREFIX_PATTERN = re.compile(
    r"^\[[A-Za-z]{3} \d{4}-\d{2}-\d{2} \d{2}:\d{2} [^\]]+\]\s"
)

_FIXED_TIMEZONES: dict[str, tzinfo] = {
    "UTC": UTC,
    "Asia/Shanghai": timezone(timedelta(hours=8), name="Asia/Shanghai"),
}


@dataclass(frozen=True)
class PromptTimezone:
    """Resolved timezone used by prompt-facing timestamp text."""

    # Display name shown to the model in runtime context.
    name: str
    # Python timezone object used for date/time conversion.
    tzinfo: tzinfo


def build_message_timestamp_prefix(
    *,
    created_at: str,
    timezone_name: str,
) -> str:
    """Build a compact immutable timestamp prefix for one stored message.

    Args:
        created_at: Message creation time from app storage.
        timezone_name: User-facing timezone preference.

    Returns:
        A prompt-visible prefix such as `[Thu 2026-06-18 20:34 GMT+08] `.
    """

    timestamp = _parse_datetime(created_at)
    prompt_timezone = resolve_prompt_timezone(timezone_name)
    local_timestamp = timestamp.astimezone(prompt_timezone.tzinfo)
    label = _offset_label(local_timestamp)
    return f"[{local_timestamp:%a %Y-%m-%d %H:%M} {label}] "


def stamp_user_message_content(
    content: str,
    *,
    created_at: str,
    timezone_name: str,
) -> str:
    """Return user content with its own timestamp prefix for the model.

    The app store keeps raw user text. This function is only for the LLM
    boundary, so historical messages remain stable across future replays.
    """

    if not content.strip():
        return content
    if TIMESTAMP_PREFIX_PATTERN.match(content):
        return content
    prefix = build_message_timestamp_prefix(
        created_at=created_at,
        timezone_name=timezone_name,
    )
    return f"{prefix}{content}"


def resolve_prompt_timezone(timezone_name: str | None) -> PromptTimezone:
    """Resolve a timezone name into a prompt display name and tzinfo.

    Invalid names fall back to UTC instead of breaking a run.
    """

    trimmed = (timezone_name or "UTC").strip() or "UTC"
    if trimmed.lower() == "local":
        local_tz = datetime.now().astimezone().tzinfo or UTC
        return PromptTimezone(
            name=f"local ({_offset_label(datetime.now(local_tz))})",
            tzinfo=local_tz,
        )
    if trimmed in _FIXED_TIMEZONES:
        return PromptTimezone(name=trimmed, tzinfo=_FIXED_TIMEZONES[trimmed])
    try:
        return PromptTimezone(name=trimmed, tzinfo=ZoneInfo(trimmed))
    except ZoneInfoNotFoundError:
        return PromptTimezone(name="UTC", tzinfo=UTC)


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO datetime, defaulting naive values to UTC."""

    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _offset_label(value: datetime) -> str:
    """Return a compact UTC/GMT offset label for prompt timestamps."""

    offset = value.utcoffset()
    if offset is None:
        return "UTC"
    total_minutes = int(offset.total_seconds() // 60)
    if total_minutes == 0:
        return "UTC"
    sign = "+" if total_minutes >= 0 else "-"
    absolute_minutes = abs(total_minutes)
    hours, minutes = divmod(absolute_minutes, 60)
    if minutes == 0:
        return f"GMT{sign}{hours:02d}"
    return f"GMT{sign}{hours:02d}:{minutes:02d}"
