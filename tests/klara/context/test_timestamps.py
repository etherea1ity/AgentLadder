from __future__ import annotations

from klara.context.timestamps import (
    build_message_timestamp_prefix,
    resolve_prompt_timezone,
    stamp_user_message_content,
)


def test_message_timestamp_prefix_uses_message_creation_time_and_timezone() -> None:
    prefix = build_message_timestamp_prefix(
        created_at="2026-06-18T12:34:56+00:00",
        timezone_name="Asia/Shanghai",
    )

    assert prefix == "[Thu 2026-06-18 20:34 GMT+08] "


def test_stamp_user_message_content_is_idempotent() -> None:
    stamped = stamp_user_message_content(
        "World Cup overall performance?",
        created_at="2026-06-18T12:34:56+00:00",
        timezone_name="Asia/Shanghai",
    )

    assert stamped == "[Thu 2026-06-18 20:34 GMT+08] World Cup overall performance?"
    assert (
        stamp_user_message_content(
            stamped,
            created_at="2026-06-18T12:35:56+00:00",
            timezone_name="Asia/Shanghai",
        )
        == stamped
    )


def test_stamp_user_message_content_leaves_blank_text_unchanged() -> None:
    assert (
        stamp_user_message_content(
            "   ",
            created_at="2026-06-18T12:34:56+00:00",
            timezone_name="Asia/Shanghai",
        )
        == "   "
    )


def test_unknown_timezone_falls_back_to_utc() -> None:
    prompt_timezone = resolve_prompt_timezone("Mars/Olympus")
    prefix = build_message_timestamp_prefix(
        created_at="2026-06-18T12:34:56+00:00",
        timezone_name="Mars/Olympus",
    )

    assert prompt_timezone.name == "UTC"
    assert prefix == "[Thu 2026-06-18 12:34 UTC] "
