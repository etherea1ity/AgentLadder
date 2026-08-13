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
    """Estimate model input tokens with a documented character heuristic."""

    characters = sum(
        len(json.dumps(message.to_public_dict(), ensure_ascii=False, sort_keys=True))
        for message in messages
    )
    return ceil(characters / chars_per_token) if characters else 0


def estimate_text_tokens(text: str, *, chars_per_token: int = 4) -> int:
    """Estimate tokens for one prompt section."""

    return ceil(len(text) / chars_per_token) if text else 0


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

    lines: list[str] = []
    if previous_summary.strip():
        lines.append(
            "Previous compacted context: "
            f"{_compact_text(previous_summary, max_chars=max_chars // 2)}"
        )
    for message in messages:
        label = message.role.capitalize()
        if message.role == "tool" and message.name:
            label = f"Tool {message.name}"
        content = _compact_text(message.content, max_chars=360)
        if content:
            lines.append(f"{label}: {content}")
    summary = "\n".join(lines)
    if len(summary) <= max_chars:
        return summary
    digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()[:12]
    return f"{summary[: max_chars - 52].rstrip()}\n[summary clipped; sha256={digest}]"


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
    summary_budget_chars = max(
        0,
        (policy.transcript_budget_tokens - message_tokens) * policy.chars_per_token,
    )
    if len(summary) > summary_budget_chars:
        summary = _compact_text(summary, max_chars=summary_budget_chars)
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


def _compact_text(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    if max_chars == 1:
        return "…"
    return compact[: max(1, max_chars - 1)].rstrip() + "…"
