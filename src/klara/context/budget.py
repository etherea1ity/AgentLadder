"""Deterministic estimation, micro-compaction, and extractive summaries."""

from __future__ import annotations

import hashlib
import json
import re
from math import ceil
from typing import Iterable

from klara.context.policy import ContextPolicy
from klara.core.messages import KlaraMessage


def estimate_message_tokens(
    messages: Iterable[KlaraMessage], *, chars_per_token: int = 4
) -> int:
    """Conservatively estimate serialized tokens across Latin and CJK text."""

    return sum(
        _estimate_serialized_tokens(
            json.dumps(message.to_public_dict(), ensure_ascii=False, sort_keys=True),
            chars_per_token=chars_per_token,
        )
        for message in messages
    )


def estimate_text_tokens(text: str, *, chars_per_token: int = 4) -> int:
    """Estimate tokens without under-counting CJK and other non-ASCII text."""

    return _estimate_serialized_tokens(text, chars_per_token=chars_per_token)


def compact_tool_message(message: KlaraMessage, *, max_chars: int) -> KlaraMessage:
    """Bound one old tool observation while preserving provenance and join ids."""

    if message.role != "tool" or len(message.content) <= max_chars:
        return message
    digest = hashlib.sha256(message.content.encode("utf-8")).hexdigest()[:12]
    clipped = _compact_text(message.content, max_chars=max_chars)
    return KlaraMessage(
        role="tool",
        name=message.name,
        tool_call_id=message.tool_call_id,
        content=(
            f"{clipped}\n[older tool observation compacted; "
            f"original_chars={len(message.content)}; sha256={digest}]"
        ),
    )


def build_extractive_summary(
    messages: Iterable[KlaraMessage],
    *,
    previous_summary: str = "",
    max_chars: int,
) -> str:
    """Build a bounded role-labelled summary without an extra model call."""

    lines: list[tuple[str, bool]] = []
    if previous_summary.strip():
        digest = hashlib.sha256(previous_summary.encode("utf-8")).hexdigest()[:12]
        lines.append(
            (
                "PreviousSummary: "
                f"{_compact_text(previous_summary, max_chars=max_chars // 2)} "
                f"[source={digest}]",
                False,
            )
        )
    for message in messages:
        label = message.role.capitalize()
        if message.role == "tool" and message.name:
            label = f"Tool {message.name}"
        content = _summary_content(message.content, max_chars=360)
        if content:
            digest = hashlib.sha256(message.content.encode("utf-8")).hexdigest()[:12]
            priority = _is_user_correction_or_constraint(message)
            instruction_anchor = (
                " [instruction_anchor="
                f"{_summary_content(message.content, max_chars=96)}]"
                if priority
                else ""
            )
            lines.append(
                (
                    f"{label}: {content} [source={digest}]{instruction_anchor}",
                    priority,
                )
            )
    # Put explicit user corrections and constraints at the durable tail. A
    # bounded head/tail clip then retains both early provenance and the latest
    # instructions instead of silently keeping only the oldest text.
    ordinary_lines = [item for item in lines if not item[1]]
    priority_lines = [item for item in lines if item[1]]
    summary = "\n".join(text for text, _ in [*ordinary_lines, *priority_lines])
    if len(summary) <= max_chars:
        return summary
    digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()[:12]
    marker = f"\n[summary clipped; sha256={digest}]\n"
    available = max(0, max_chars - len(marker))
    head = available // 2
    tail = available - head
    return f"{summary[:head].rstrip()}{marker}{summary[-tail:].lstrip()}"[:max_chars]


def compact_transcript(
    messages: list[KlaraMessage],
    *,
    policy: ContextPolicy,
    previous_summary: str = "",
) -> tuple[list[KlaraMessage], str, dict[str, int | str | bool]]:
    """Keep recent messages, summarize older material, and satisfy the budget."""

    before_tokens = estimate_message_tokens(
        messages, chars_per_token=policy.chars_per_token
    ) + estimate_text_tokens(previous_summary, chars_per_token=policy.chars_per_token)
    recent_start = max(0, len(messages) - policy.recent_messages)
    prepared = [
        compact_tool_message(message, max_chars=policy.tool_result_max_chars)
        if index < recent_start
        else message
        for index, message in enumerate(messages)
    ]
    micro_compacted = sum(
        original.content != compacted.content
        for original, compacted in zip(messages, prepared)
    )
    omitted: list[KlaraMessage] = []
    summary = previous_summary
    while (
        estimate_message_tokens(prepared, chars_per_token=policy.chars_per_token)
        + estimate_text_tokens(summary, chars_per_token=policy.chars_per_token)
        > policy.transcript_budget_tokens
        and len(prepared) > policy.minimum_recent_messages
    ):
        requested_drop = max(1, len(prepared) - policy.recent_messages)
        drop_count = _safe_prefix_drop_count(prepared, requested_drop)
        if drop_count <= 0:
            break
        omitted.extend(prepared[:drop_count])
        prepared = prepared[drop_count:]
        summary = build_extractive_summary(
            omitted,
            previous_summary=previous_summary,
            max_chars=policy.summary_max_chars,
        )
    hard_trimmed = 0
    for index, message in enumerate(prepared):
        current_tokens = estimate_message_tokens(
            prepared, chars_per_token=policy.chars_per_token
        ) + estimate_text_tokens(summary, chars_per_token=policy.chars_per_token)
        if current_tokens <= policy.transcript_budget_tokens:
            break
        excess_chars = (current_tokens - policy.transcript_budget_tokens) * policy.chars_per_token
        target_chars = max(64, len(message.content) - excess_chars - 96)
        if len(message.content) <= target_chars:
            continue
        prepared[index] = _hard_trim_message(message, max_chars=target_chars)
        hard_trimmed += 1
    # An unusually small custom budget can make the preferred recent-message
    # floor impossible. The model window is the hard boundary, so retain the
    # newest message and sacrifice older material deterministically.
    while (
        estimate_message_tokens(prepared, chars_per_token=policy.chars_per_token)
        > policy.transcript_budget_tokens
        and len(prepared) > 1
    ):
        omitted.append(prepared.pop(0))
        summary = build_extractive_summary(
            omitted,
            previous_summary=previous_summary,
            max_chars=policy.summary_max_chars,
        )
    if prepared and (
        estimate_message_tokens(prepared, chars_per_token=policy.chars_per_token)
        > policy.transcript_budget_tokens
    ):
        fitted = _fit_message_to_budget(
            prepared[0],
            budget_tokens=policy.transcript_budget_tokens,
            chars_per_token=policy.chars_per_token,
        )
        hard_trimmed += fitted.content != prepared[0].content
        prepared[0] = fitted
    message_tokens = estimate_message_tokens(
        prepared, chars_per_token=policy.chars_per_token
    )
    summary_budget_tokens = max(
        0, policy.transcript_budget_tokens - message_tokens
    )
    summary = _fit_text_to_budget(
        summary,
        budget_tokens=summary_budget_tokens,
        chars_per_token=policy.chars_per_token,
    )
    after_tokens = estimate_message_tokens(
        prepared, chars_per_token=policy.chars_per_token
    ) + estimate_text_tokens(summary, chars_per_token=policy.chars_per_token)
    summary_hash = (
        hashlib.sha256(summary.encode("utf-8")).hexdigest() if summary else ""
    )
    return prepared, summary, {
        "before_estimated_tokens": before_tokens,
        "after_estimated_tokens": after_tokens,
        "budget_tokens": policy.transcript_budget_tokens,
        "messages_before": len(messages),
        "messages_after": len(prepared),
        "messages_summarized": len(omitted),
        "tool_results_micro_compacted": micro_compacted,
        "messages_hard_trimmed": hard_trimmed,
        "summary_present": bool(summary),
        "summary_sha256": summary_hash,
    }


def _safe_prefix_drop_count(messages: list[KlaraMessage], requested: int) -> int:
    """Avoid retaining a leading tool result without its assistant request."""

    count = min(requested, max(0, len(messages) - 1))
    while count < len(messages) and messages[count].role == "tool":
        count += 1
    return min(count, max(0, len(messages) - 1))


def _hard_trim_message(message: KlaraMessage, *, max_chars: int) -> KlaraMessage:
    """Bound an individually oversized message with a visible digest marker."""

    digest = hashlib.sha256(message.content.encode("utf-8")).hexdigest()[:12]
    marker = f"\n[message clipped for context budget; sha256={digest}]\n"
    if max_chars <= len(marker):
        content = f"[clipped; sha256={digest}]"[:max_chars]
        return KlaraMessage(
            role=message.role,
            content=content,
            name=message.name,
            tool_call_id=message.tool_call_id,
            tool_calls=message.tool_calls,
        )
    available = max(2, max_chars - len(marker))
    head = available * 2 // 3
    tail = available - head
    content = f"{message.content[:head].rstrip()}{marker}{message.content[-tail:].lstrip()}"
    return KlaraMessage(
        role=message.role,
        content=content,
        name=message.name,
        tool_call_id=message.tool_call_id,
        tool_calls=message.tool_calls,
    )


def _fit_message_to_budget(
    message: KlaraMessage,
    *,
    budget_tokens: int,
    chars_per_token: int,
) -> KlaraMessage:
    """Binary-search a content bound that fits one unavoidable latest message."""

    low = 0
    high = len(message.content)
    best = _hard_trim_message(message, max_chars=0)
    while low <= high:
        middle = (low + high) // 2
        candidate = _hard_trim_message(message, max_chars=middle)
        if (
            estimate_message_tokens([candidate], chars_per_token=chars_per_token)
            <= budget_tokens
        ):
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _fit_text_to_budget(
    text: str,
    *,
    budget_tokens: int,
    chars_per_token: int,
) -> str:
    """Binary-search a text bound using the same multilingual estimator."""

    if budget_tokens <= 0 or not text:
        return ""
    if estimate_text_tokens(text, chars_per_token=chars_per_token) <= budget_tokens:
        return text
    low = 0
    high = len(text)
    best = ""
    while low <= high:
        middle = (low + high) // 2
        candidate = _compact_text_head_tail(text, max_chars=middle)
        if estimate_text_tokens(candidate, chars_per_token=chars_per_token) <= budget_tokens:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _estimate_serialized_tokens(text: str, *, chars_per_token: int) -> int:
    """Use one token per non-ASCII code point and the configured Latin ratio."""

    if not text:
        return 0
    ascii_chars = sum(ord(char) < 128 for char in text)
    non_ascii_chars = len(text) - ascii_chars
    return ceil(ascii_chars / chars_per_token) + non_ascii_chars


def _is_user_correction_or_constraint(message: KlaraMessage) -> bool:
    """Identify user-authored facts whose loss most often changes intent."""

    if message.role != "user":
        return False
    normalized = message.content.casefold()
    cues = (
        "actually",
        "instead",
        "correction",
        "must ",
        "must not",
        "do not",
        "don't",
        "only ",
        "改成",
        "更正",
        "不是",
        "不要",
        "必须",
        "只能",
    )
    return any(cue in normalized for cue in cues)


def _summary_content(text: str, *, max_chars: int) -> str:
    """Keep prompt timestamps while placing semantic content before metadata."""

    match = re.match(r"^(\[[A-Za-z]{3} [^\]]+\])\s+(.+)$", text, re.DOTALL)
    if match is not None:
        text = f"{match.group(2)} {match.group(1)}"
    return _compact_text(text, max_chars=max_chars)


def _compact_text_head_tail(text: str, *, max_chars: int) -> str:
    """Bound summary text while retaining both original context and corrections."""

    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    marker = " [context clipped] "
    if max_chars <= len(marker) + 2:
        return compact[-max_chars:] if max_chars > 0 else ""
    available = max_chars - len(marker)
    head = available // 2
    tail = available - head
    return f"{compact[:head].rstrip()}{marker}{compact[-tail:].lstrip()}"


def _compact_text(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    if max_chars == 1:
        return "…"
    return compact[: max(1, max_chars - 1)].rstrip() + "…"
