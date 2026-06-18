"""Runtime context prompt assembly for Klara model calls."""

from __future__ import annotations

from datetime import UTC, datetime

from klara.context.timestamps import resolve_prompt_timezone


def build_runtime_context_prompt(
    *,
    timezone_name: str,
    now: datetime | None = None,
) -> str:
    """Build the small date anchor appended to Klara's system prompt.

    Args:
        timezone_name: User-facing timezone preference.
        now: Optional clock value for deterministic tests.

    Returns:
        A date-only runtime context block. Exact wall-clock time remains a tool
        responsibility so the system prompt stays stable during the day.
    """

    current_utc = _aware_utc(now or datetime.now(UTC))
    prompt_timezone = resolve_prompt_timezone(timezone_name)
    local_now = current_utc.astimezone(prompt_timezone.tzinfo)
    return "\n".join(
        [
            "<runtime_context>",
            f"Conversation date: {local_now:%A, %B %d, %Y}",
            f"User timezone: {prompt_timezone.name}",
            f"UTC date: {current_utc.date().isoformat()}",
            (
                "The conversation date is already provided here; do not call "
                "current_time only to learn today's date."
            ),
            (
                "For live/current/latest/today/so-far/news/sports/scores/"
                "schedules/prices/versions, call web_search before answering "
                "from memory."
            ),
            (
                "Call current_time only for exact wall-clock time, weekday, "
                "timezone conversion, or relative date/time arithmetic."
            ),
            (
                "Call web_fetch only when you need to read a specific public URL "
                "returned by search or provided by the user."
            ),
            "</runtime_context>",
        ]
    )


def build_system_prompt(
    *,
    persona: str,
    timezone_name: str,
    now: datetime | None = None,
) -> str:
    """Append runtime context to the static Klara persona prompt."""

    return "\n\n".join(
        [
            persona.strip(),
            build_runtime_context_prompt(timezone_name=timezone_name, now=now),
        ]
    ).strip()


def _aware_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime from a caller-provided clock value."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
