from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.api.schemas import RunEventRecord, RunEventType
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

    def add(self, usage: dict[str, Any], *, token_source: str | None = None) -> None:
        """Add one provider usage payload when token fields are present."""

        payload = _usage_payload(usage)
        if token_source == "reported" or any(value is not None for value in payload.values()):
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
            metrics = _dict_payload(event.payload.get("metrics"))
            usage_fields = _usage_payload(usage)
            token_source = _token_source(metrics, usage_fields)
            duration_ms = _int_or_none(metrics.get("duration_ms"))
            self.usage_totals.add(usage, token_source=token_source)
            return (
                ProjectedRunEvent(
                    event_type="llm_call_completed",
                    message="Model call completed.",
                    payload={
                        "turn_index": event.payload.get("turn_index"),
                        "tool_call_count": event.payload.get("tool_call_count"),
                        "usage": usage,
                        "finalization": bool(event.payload.get("finalization", False)),
                        **usage_fields,
                        "duration_ms": duration_ms,
                        "latency_ms": duration_ms,
                        "token_source": token_source,
                        "metrics": {
                            **usage_fields,
                            "duration_ms": duration_ms,
                            "token_source": token_source,
                        },
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
                        "started_at": event.payload.get("started_at"),
                    },
                ),
            )
        if event.type in {"tool.completed", "tool.failed"}:
            tool_result = _compact_tool_result(
                _dict_payload(event.payload.get("tool_result"))
            )
            metrics = _dict_payload(event.payload.get("metrics"))
            duration_ms = _int_or_none(metrics.get("duration_ms"))
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
                        "started_at": event.payload.get("started_at"),
                        "completed_at": event.payload.get("completed_at"),
                        "duration_ms": duration_ms,
                        "latency_ms": duration_ms,
                        "metrics": {"duration_ms": duration_ms},
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


def project_activity_item(event: RunEventRecord) -> ProjectedRunEvent | None:
    """Return one public activity item derived from a persisted run event."""

    if event.event_type == "activity_item_upserted":
        return None
    item = _activity_item_for_event(event)
    if item is None:
        return None
    return ProjectedRunEvent(
        event_type="activity_item_upserted",
        message=item["title"],
        payload={"item": item},
    )


def _activity_item_for_event(event: RunEventRecord) -> dict[str, Any] | None:
    """Build a sanitized GPT-like activity item from a public run event."""

    if event.event_type == "run_created":
        return _activity_item(
            event,
            title="Preparing the run",
            body="Klara is setting up the runtime for this request.",
            status="running",
            kind="orientation",
        )
    if event.event_type == "thinking_started":
        return _activity_item(
            event,
            title="Preparing the run",
            body="Klara is setting up the runtime for this request.",
            status="running",
            kind="orientation",
        )
    if event.event_type == "llm_call_started":
        return _activity_item(
            event,
            title="Reading the request",
            body="Klara is asking the selected model to process the request.",
            status="running",
            kind="orientation",
        )
    if event.event_type == "llm_call_completed":
        return _activity_item(
            event,
            title="Model response received",
            body="The model returned a response for this step.",
            status="completed",
            kind="orientation",
        )
    if event.event_type == "tool_call_started":
        return _tool_activity_started(event)
    if event.event_type == "tool_call_completed":
        return _tool_activity_completed(event)
    if event.event_type == "tool_call_failed":
        return _tool_activity_failed(event)
    if event.event_type == "answer_streaming_started":
        return _activity_item(
            event,
            title="Writing the answer",
            body="Klara is turning the verified context into the final response.",
            status="running",
            kind="composition",
        )
    if event.event_type == "run_completed":
        return _activity_item(
            event,
            title="Run completed",
            body="Klara finished the runtime path for this response.",
            status="completed",
            kind="finalization",
        )
    return None


def _tool_activity_started(event: RunEventRecord) -> dict[str, Any]:
    """Return a sanitized activity item for a tool start event."""

    name = _tool_call_name(event)
    if name == "web_search":
        return _activity_item(
            event,
            title="Looking up public information",
            body="Klara is checking external sources before answering.",
            status="running",
            kind="evidence",
        )
    if name == "web_fetch":
        return _activity_item(
            event,
            title="Opening source material",
            body="Klara is reading a selected source to verify details.",
            status="running",
            kind="evidence",
        )
    return _activity_item(
        event,
        title=f"Using {name}",
        body="Klara is using a runtime tool for this step.",
        status="running",
        kind="tool_activity",
    )


def _tool_activity_completed(event: RunEventRecord) -> dict[str, Any]:
    """Return a sanitized activity item for a tool completion event."""

    name = _tool_result_name(event)
    if name == "web_search":
        return _activity_item(
            event,
            title="Search results returned",
            body="Klara received candidate sources and can decide what to verify next.",
            status="completed",
            kind="evidence",
        )
    if name == "web_fetch":
        return _activity_item(
            event,
            title="Source material reviewed",
            body="Klara received content from a selected source.",
            status="completed",
            kind="evidence",
        )
    return _activity_item(
        event,
        title=f"{name} returned",
        body="Klara received an observation from a runtime tool.",
        status="completed",
        kind="tool_activity",
    )


def _tool_activity_failed(event: RunEventRecord) -> dict[str, Any]:
    """Return a sanitized activity item for a failed tool event."""

    name = _tool_result_name(event)
    return _activity_item(
        event,
        title=f"{name} failed",
        body="A runtime tool did not return a usable observation for this step.",
        status="failed",
        kind="tool_activity",
    )


def _activity_item(
    event: RunEventRecord,
    *,
    title: str,
    body: str,
    status: str,
    kind: str,
) -> dict[str, Any]:
    """Return the shared public activity item shape."""

    return {
        "id": f"act_{event.event_id}",
        "title": title,
        "body": body,
        "status": status,
        "kind": kind,
        "source": "runtime_event",
        "evidence_event_ids": [event.event_id],
        "confidence": 1.0,
    }


def _tool_call_name(event: RunEventRecord) -> str:
    """Return a public tool name from a tool-call-started event."""

    tool_call = event.payload.get("tool_call")
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "tool")
    return "tool"


def _tool_result_name(event: RunEventRecord) -> str:
    """Return a public tool name from a tool terminal event."""

    tool_result = event.payload.get("tool_result")
    if isinstance(tool_result, dict):
        return str(tool_result.get("name") or "tool")
    return "tool"


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

    prompt = _int_or_none(_first_present(usage, "prompt_tokens", "input_tokens"))
    completion = _int_or_none(
        _first_present(usage, "completion_tokens", "output_tokens")
    )
    total = _int_or_none(_first_present(usage, "total_tokens"))
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _token_source(
    metrics: dict[str, Any],
    usage_fields: dict[str, int | None],
) -> str:
    """Return a stable token-source label for one projected LLM call."""

    source = metrics.get("token_source")
    if source in {"reported", "estimated", "unknown"}:
        return str(source)
    if any(value is not None for value in usage_fields.values()):
        return "reported"
    return "unknown"


def _first_present(usage: dict[str, Any], *keys: str) -> Any:
    """Return the first present value from a usage dictionary."""

    for key in keys:
        if key in usage:
            return usage[key]
    return None


def _int_or_none(value: Any) -> int | None:
    """Return an integer token count when the value is numeric."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
