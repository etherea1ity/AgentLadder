from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from apps.api.schemas import RunEventRecord
from klara.core.loop import LlmClient
from klara.core.messages import KlaraMessage

MAX_NOTE_CHARS = 180
MAX_SUMMARY_CHARS = 260


@dataclass(frozen=True)
class WorkstreamNarratorInput:
    """Public runtime state available to the optional legacy narrator."""

    user_request: str
    selected_model: str
    run_status: str
    phase: str
    elapsed_ms: int
    recent_events: tuple[RunEventRecord, ...]
    previous_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkstreamNote:
    """Validated legacy narrator note ready for RunEvent persistence."""

    text: str
    evidence_event_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class ThinkingSummaryInput:
    """Completed public trace available to the thinking summary narrator."""

    user_request: str
    selected_model: str
    run_status: str
    duration_ms: int
    events: tuple[RunEventRecord, ...]
    tool_summaries: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ThinkingSummaryResult:
    """Validated visible thinking summary ready for RunEvent persistence."""

    summary: str
    evidence_event_ids: tuple[str, ...]
    confidence: float


class WorkstreamNarrator:
    """Generate short evidence-bound notes from public run events.

    This class is kept for compatibility with existing workstream_note events.
    The default RunService path uses ThinkingSummaryNarrator instead.
    """

    def __init__(
        self,
        *,
        client: LlmClient,
        model: str,
        prompt_path: Path | None = None,
    ) -> None:
        """Create a narrator backed by an injected model client."""

        self.client = client
        self.model = model
        self.prompt_path = prompt_path or (
            Path("src") / "klara" / "prompts" / "workstream_narrator.md"
        )

    def create_note(self, payload: WorkstreamNarratorInput) -> WorkstreamNote | None:
        """Return a validated note or None when no safe note should emit."""

        response = self.client.complete(
            system_prompt=self._prompt(),
            messages=(
                KlaraMessage(
                    role="user",
                    content=json.dumps(_workstream_input_payload(payload), ensure_ascii=False),
                ),
            ),
            tools=(),
            model=self.model,
        )
        try:
            raw = json.loads(response.content)
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, dict) or raw.get("emit") is not True:
            return None
        text = str(raw.get("text") or "").strip()
        if not text:
            return None
        if text in payload.previous_notes:
            return None
        if _contains_forbidden_reasoning_terms(text):
            return None
        if not _claims_have_evidence(text, payload.recent_events):
            return None
        evidence_ids = _valid_evidence_ids(raw.get("evidence_event_ids"), payload.recent_events)
        if not evidence_ids:
            return None
        confidence = _confidence(raw.get("confidence"))
        return WorkstreamNote(
            text=text[:MAX_NOTE_CHARS],
            evidence_event_ids=tuple(evidence_ids),
            confidence=confidence,
        )

    def _prompt(self) -> str:
        """Read the narrator instruction prompt."""

        return self.prompt_path.read_text(encoding="utf-8")


class ThinkingSummaryNarrator:
    """Generate a completed-run summary from public trace events."""

    def __init__(
        self,
        *,
        client: LlmClient,
        model: str,
        prompt_path: Path | None = None,
    ) -> None:
        """Create a thinking summary narrator backed by an injected model."""

        self.client = client
        self.model = model
        self.prompt_path = prompt_path or (
            Path("src") / "klara" / "prompts" / "thinking_summary_narrator.md"
        )

    def create_summary(
        self,
        payload: ThinkingSummaryInput,
    ) -> ThinkingSummaryResult | None:
        """Return a validated visible summary or None."""

        response = self.client.complete(
            system_prompt=self._prompt(),
            messages=(
                KlaraMessage(
                    role="user",
                    content=json.dumps(_thinking_summary_input_payload(payload), ensure_ascii=False),
                ),
            ),
            tools=(),
            model=self.model,
        )
        try:
            raw = json.loads(response.content)
        except json.JSONDecodeError:
            return None
        if not isinstance(raw, dict):
            return None
        summary = str(raw.get("summary") or "").strip()
        if not summary:
            return None
        if _contains_forbidden_reasoning_terms(summary):
            return None
        if not _claims_have_evidence(summary, payload.events):
            return None
        evidence_ids = _valid_evidence_ids(raw.get("evidence_event_ids"), payload.events)
        if not evidence_ids:
            return None
        return ThinkingSummaryResult(
            summary=summary[:MAX_SUMMARY_CHARS],
            evidence_event_ids=tuple(evidence_ids),
            confidence=_confidence(raw.get("confidence")),
        )

    def _prompt(self) -> str:
        """Read the thinking summary narrator instruction prompt."""

        return self.prompt_path.read_text(encoding="utf-8")


def _workstream_input_payload(payload: WorkstreamNarratorInput) -> dict[str, Any]:
    """Build the strict public JSON input for the legacy narrator model."""

    return {
        "user_request": payload.user_request,
        "selected_model": payload.selected_model,
        "run_status": payload.run_status,
        "phase": payload.phase,
        "elapsed_ms": payload.elapsed_ms,
        "recent_events": [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "message": event.message,
                "safe_summary": _safe_event_summary(event),
            }
            for event in payload.recent_events
        ],
        "previous_notes": list(payload.previous_notes),
    }


def _thinking_summary_input_payload(payload: ThinkingSummaryInput) -> dict[str, Any]:
    """Build the strict public JSON input for the thinking summary narrator."""

    return {
        "user_request": payload.user_request,
        "selected_model": payload.selected_model,
        "run_status": payload.run_status,
        "duration_ms": payload.duration_ms,
        "events": [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "message": event.message,
                "safe_summary": _safe_event_summary(event),
                "metrics": _safe_event_metrics(event),
            }
            for event in payload.events
        ],
        "tool_summaries": list(payload.tool_summaries),
    }


def _safe_event_summary(event: RunEventRecord) -> str:
    """Return a compact event summary without raw content payloads."""

    if event.event_type == "tool_call_started":
        tool_call = event.payload.get("tool_call")
        name = tool_call.get("name") if isinstance(tool_call, dict) else None
        return f"tool started: {name or 'tool'}"
    if event.event_type in {"tool_call_completed", "tool_call_failed"}:
        tool_result = event.payload.get("tool_result")
        if isinstance(tool_result, dict):
            name = str(tool_result.get("name") or "tool")
            ok = tool_result.get("ok")
            preview = str(tool_result.get("content_preview") or "")[:120]
            if preview:
                return f"tool result: {name}, ok={ok}, preview={preview}"
            return f"tool result: {name}, ok={ok}"
    return event.message[:160]


def _safe_event_metrics(event: RunEventRecord) -> dict[str, Any]:
    """Return compact public metrics for narrator input."""

    raw_metrics = event.payload.get("metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
    public: dict[str, Any] = {}
    for key in (
        "duration_ms",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "token_source",
    ):
        if key in metrics:
            public[key] = metrics[key]
        elif key in event.payload:
            public[key] = event.payload[key]
    return public


def _valid_evidence_ids(value: object, events: tuple[RunEventRecord, ...]) -> list[str]:
    """Filter evidence ids to ids that exist in public events."""

    if not isinstance(value, list):
        return []
    known = {event.event_id for event in events}
    return [item for item in value if isinstance(item, str) and item in known]


def _contains_forbidden_reasoning_terms(text: str) -> bool:
    """Return whether text exposes or imitates hidden reasoning."""

    lowered = text.lower()
    forbidden = (
        "chain-of-thought",
        "chain of thought",
        "scratchpad",
        "hidden reasoning",
        "raw reasoning",
        "my chain-of-thought",
        "i realized",
        "i inferred",
    )
    return any(term in lowered for term in forbidden)


def _claims_have_evidence(text: str, events: tuple[RunEventRecord, ...]) -> bool:
    """Reject action claims that are unsupported by public events."""

    lowered = text.lower()
    checks = [
        (("search", "searched"), _has_search_event),
        (("read", "opened", "fetched"), _has_read_event),
        (("edit", "edited", "modify", "modified"), _has_edit_event),
        (("verify", "verified", "test", "tested"), _has_verify_event),
        (("tool",), _has_tool_event),
    ]
    for terms, predicate in checks:
        if any(term in lowered for term in terms) and not predicate(events):
            return False
    return True


def _has_tool_event(events: tuple[RunEventRecord, ...]) -> bool:
    """Return whether public events show tool activity."""

    return any(event.event_type.startswith("tool_call_") for event in events)


def _has_search_event(events: tuple[RunEventRecord, ...]) -> bool:
    """Return whether public events show search activity."""

    return any(_event_mentions(event, ("search", "web_search")) for event in events)


def _has_read_event(events: tuple[RunEventRecord, ...]) -> bool:
    """Return whether public events show read/fetch activity."""

    return any(_event_mentions(event, ("read", "fetch", "open", "web_fetch")) for event in events)


def _has_edit_event(events: tuple[RunEventRecord, ...]) -> bool:
    """Return whether public events show edit activity."""

    return any(_event_mentions(event, ("edit", "modify", "write")) for event in events)


def _has_verify_event(events: tuple[RunEventRecord, ...]) -> bool:
    """Return whether public events show verification activity."""

    return any(_event_mentions(event, ("verify", "test", "check")) for event in events)


def _event_mentions(event: RunEventRecord, needles: tuple[str, ...]) -> bool:
    """Return whether an event's public shape contains any needle."""

    text = json.dumps(
        {
            "event_type": event.event_type,
            "message": event.message,
            "payload": event.payload,
        },
        ensure_ascii=False,
    ).lower()
    return any(needle in text for needle in needles)


def _confidence(value: object) -> float:
    """Normalize model-provided confidence."""

    if not isinstance(value, int | float) or isinstance(value, bool):
        return 0.0
    return max(0.0, min(float(value), 1.0))
