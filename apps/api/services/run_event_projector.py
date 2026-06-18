from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.api.schemas import RunEventType
from klara.core.events import KlaraEvent


@dataclass(frozen=True)
class ProjectedRunEvent:
    """Frontend-visible event produced from one public core lifecycle event."""

    event_type: RunEventType
    message: str
    payload: dict[str, Any]


class UsageTotals:
    """Accumulate provider token usage across projected LLM events."""

    def __init__(self) -> None:
        """Create an empty usage accumulator."""

        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.has_reported = False

    def add(self, usage: dict[str, Any]) -> None:
        """Add one provider usage payload when token fields are present."""

        payload = _usage_payload(usage)
        if any(value is not None for value in payload.values()):
            self.has_reported = True
        self.prompt_tokens += payload["prompt_tokens"] or 0
        self.completion_tokens += payload["completion_tokens"] or 0
        self.total_tokens += payload["total_tokens"] or 0


class RunEventProjector:
    """Project public Klara lifecycle events into API/SSE run events."""

    def __init__(
        self,
        *,
        selected_model: str | None = None,
        usage_totals: UsageTotals | None = None,
    ) -> None:
        """Create a projector for one app run."""

        self.selected_model = selected_model
        self.usage_totals = usage_totals or UsageTotals()

    def project(self, event: KlaraEvent) -> tuple[ProjectedRunEvent, ...]:
        """Return API events derived from one public core event."""

        if event.type == "llm.started":
            return (
                ProjectedRunEvent(
                    event_type="llm_call_started",
                    message="Klara is calling the model.",
                    payload={
                        "turn_index": event.payload.get("turn_index"),
                        "model": event.payload.get("model") or self.selected_model,
                        "finalization": bool(event.payload.get("finalization", False)),
                    },
                ),
            )
        if event.type == "llm.completed":
            usage = (
                event.payload.get("usage")
                if isinstance(event.payload.get("usage"), dict)
                else {}
            )
            self.usage_totals.add(usage)
            return (
                ProjectedRunEvent(
                    event_type="llm_call_completed",
                    message="Model call completed.",
                    payload={
                        "turn_index": event.payload.get("turn_index"),
                        "tool_call_count": event.payload.get("tool_call_count"),
                        "usage": usage,
                        "finalization": bool(event.payload.get("finalization", False)),
                        **_usage_payload(usage),
                    },
                ),
            )
        if event.type == "tool.started":
            tool_call = _dict_payload(event.payload.get("tool_call"))
            name = str(tool_call.get("name") or "tool")
            return (
                ProjectedRunEvent(
                    event_type="tool_call_started",
                    message=f"Klara is using {name}.",
                    payload={
                        "turn_index": event.payload.get("turn_index"),
                        "tool_call": tool_call,
                    },
                ),
            )
        if event.type in {"tool.completed", "tool.failed"}:
            tool_result = _compact_tool_result(
                _dict_payload(event.payload.get("tool_result"))
            )
            name = str(tool_result.get("name") or "tool")
            failed = event.type == "tool.failed" or tool_result.get("ok") is False
            return (
                ProjectedRunEvent(
                    event_type=(
                        "tool_call_failed" if failed else "tool_call_completed"
                    ),
                    message=(
                        f"{name} failed."
                        if failed
                        else f"{name} returned an observation."
                    ),
                    payload={
                        "turn_index": event.payload.get("turn_index"),
                        "tool_result": tool_result,
                        "blocked": bool(event.payload.get("blocked", False)),
                    },
                ),
            )
        if event.type == "tool_policy.stopped":
            return (
                ProjectedRunEvent(
                    event_type="policy_stop",
                    message="Tool policy stopped further tool calls.",
                    payload={
                        "core_event_type": event.type,
                        "turn_index": event.payload.get("turn_index"),
                        "stop_reason": event.payload.get("stop_reason"),
                        "reason": event.payload.get("reason"),
                    },
                ),
            )

        hook_projection = _hook_projection(event)
        if hook_projection is not None:
            return (hook_projection,)

        return ()


def _hook_projection(event: KlaraEvent) -> ProjectedRunEvent | None:
    """Return compact hook placement projection when the event is a hook event."""

    placement_by_prefix = {
        "user_prompt_submit": "UserPromptSubmit",
        "pre_tool_use": "PreToolUse",
        "post_tool_use": "PostToolUse",
        "stop": "Stop",
    }
    prefix, _, suffix = event.type.partition(".")
    placement = placement_by_prefix.get(prefix)
    if placement is None or suffix not in {"started", "completed"}:
        return None
    payload: dict[str, Any] = {
        "placement": placement,
        "core_event_type": event.type,
        "turn_index": event.payload.get("turn_index"),
    }
    if "allowed" in event.payload:
        payload["allowed"] = event.payload.get("allowed")
    if "reason" in event.payload:
        payload["reason"] = event.payload.get("reason")
    return ProjectedRunEvent(
        event_type=(
            "hook_placement_started"
            if suffix == "started"
            else "hook_placement_completed"
        ),
        message=f"{placement} hook {suffix}.",
        payload=payload,
    )


def _compact_tool_result(tool_result: dict[str, Any]) -> dict[str, Any]:
    """Remove full content from frontend-facing tool result projection."""

    return {
        key: value
        for key, value in tool_result.items()
        if key != "content"
    }


def _dict_payload(value: object) -> dict[str, Any]:
    """Return a dict payload when the event field is dictionary-shaped."""

    if isinstance(value, dict):
        return dict(value)
    return {}


def _usage_payload(usage: dict[str, Any]) -> dict[str, int | None]:
    """Normalize common OpenAI-compatible usage field names."""

    prompt = _int_or_none(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _int_or_none(
        usage.get("completion_tokens") or usage.get("output_tokens")
    )
    total = _int_or_none(usage.get("total_tokens"))
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _int_or_none(value: Any) -> int | None:
    """Return an integer token count when the value is numeric."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
