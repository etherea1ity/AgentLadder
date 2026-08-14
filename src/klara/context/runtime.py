"""Runtime context prompt assembly for Klara model calls."""

from __future__ import annotations

from datetime import UTC, datetime

from klara.context.timestamps import resolve_prompt_timezone


def build_runtime_context_prompt(
    *,
    timezone_name: str,
    now: datetime | None = None,
    capabilities: tuple[str, ...] | None = None,
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
    available = None if capabilities is None else frozenset(capabilities)
    lines = [
        "<runtime_context>",
        f"Conversation date: {local_now:%A, %B %d, %Y}",
        f"User timezone: {prompt_timezone.name}",
        f"UTC date: {current_utc.date().isoformat()}",
    ]
    if available is None or "current_time" in available:
        lines.extend(
            [
                (
                    "The conversation date is already provided here; do not call "
                    "current_time only to learn today's date."
                ),
                (
                    "Call current_time only for exact wall-clock time, weekday, "
                    "timezone conversion, or relative date/time arithmetic."
                ),
            ]
        )
    if available is None or "web_search" in available:
        lines.extend(
            [
                (
                    "For live/current/latest/today/so-far/news/sports/scores/"
                    "schedules/prices/versions, call web_search before answering "
                    "from memory."
                ),
                (
                    "Keep web_search queries faithful to the user's scope and named "
                    "entities."
                ),
                (
                    "Search snippets are candidates, not evidence. Do not conclude "
                    "from snippets alone when a factual answer depends on source text."
                ),
                (
                    "If fetched pages disagree, do not merge conflicting claims. "
                    "Prefer claims that are directly supported by fetched text, "
                    "dated clearly, and relevant to the user's request; otherwise "
                    "call out uncertainty."
                ),
                (
                    "For web-backed summaries, do not invent quotes, numeric "
                    "ratings, awards, statistics, or per-item commentary that fetched "
                    "text does not state."
                ),
            ]
        )
    if available is None or "web_fetch" in available:
        lines.append(
            "Call web_fetch for source text from a specific public URL returned by "
            "search or provided by the user."
        )
    if available is None or "todo_write" in available:
        lines.append(
            "For multi-step work, call todo_write before substantive actions; keep "
            "one item in_progress, update scope changes, and mark verified steps "
            "completed. Answer simple or one-step requests directly."
        )
    lines.append("</runtime_context>")
    return "\n".join(lines)


def build_system_prompt(
    *,
    persona: str,
    timezone_name: str,
    now: datetime | None = None,
    capabilities: tuple[str, ...] | None = None,
) -> str:
    """Append runtime context to the static Klara persona prompt."""

    return "\n\n".join(
        [
            persona.strip(),
            build_runtime_context_prompt(
                timezone_name=timezone_name,
                now=now,
                capabilities=capabilities,
            ),
        ]
    ).strip()


def _aware_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime from a caller-provided clock value."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
