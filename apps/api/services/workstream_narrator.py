from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.api.schemas import RunEventRecord
from klara.core.loop import LlmClient
from klara.core.messages import KlaraMessage

MAX_NOTE_CHARS = 180
MAX_SUMMARY_CHARS = 260
MAX_ACTIVITY_TITLE_CHARS = 90
MAX_ACTIVITY_BODY_CHARS = 240
MIN_ACTIVITY_ITEMS = 1
MAX_ACTIVITY_ITEMS = 5
ACTIVITY_KINDS = {
    "orientation",
    "evidence",
    "tool_activity",
    "composition",
    "finalization",
    "error",
}


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
class ThinkingActivityInput:
    """Completed public facts available to the activity narrator."""

    user_request: str
    selected_model: str
    run_status: str
    duration_ms: int
    events: tuple[RunEventRecord, ...]
    activity_facts: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ThinkingActivityResult:
    """Validated visible activity summary ready for RunEvent persistence."""

    summary: str
    evidence_event_ids: tuple[str, ...]
    confidence: float
    items: tuple[dict[str, Any], ...] = ()


class WorkstreamNarrator:
    """Generate short evidence-bound notes from public run events.

    This class is kept for compatibility with existing workstream_note events.
    The default RunService path uses ThinkingActivityNarrator instead.
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


class ThinkingActivityNarrator:
    """Generate completed-run public activity from structured facts."""

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
            Path("src") / "klara" / "prompts" / "thinking_activity_narrator.md"
        )
        self.last_rejection_reason: str | None = None

    def create_summary(
        self,
        payload: ThinkingActivityInput,
    ) -> ThinkingActivityResult | None:
        """Return validated public activity or None."""

        self.last_rejection_reason = None
        response = self.client.complete(
            system_prompt=self._prompt(),
            messages=(
                KlaraMessage(
                    role="user",
                    content=json.dumps(_thinking_activity_input_payload(payload), ensure_ascii=False),
                ),
            ),
            tools=(),
            model=self.model,
        )
        try:
            raw = json.loads(response.content)
        except json.JSONDecodeError:
            self.last_rejection_reason = "invalid_json"
            return None
        if not isinstance(raw, dict):
            self.last_rejection_reason = "invalid_json"
            return None
        summary = str(raw.get("text") or raw.get("summary") or "").strip()
        if summary and _contains_forbidden_reasoning_terms(summary):
            self.last_rejection_reason = "unsupported_claim"
            return None
        items = _summary_activity_items(
            raw.get("items"),
            payload.events,
            payload.activity_facts,
        )
        if not items:
            self.last_rejection_reason = "no_items"
            return None
        evidence_ids = _aggregate_evidence_ids(items)
        return ThinkingActivityResult(
            summary=summary[:MAX_SUMMARY_CHARS],
            evidence_event_ids=tuple(evidence_ids),
            confidence=_average_confidence(items),
            items=tuple(items),
        )

    def _prompt(self) -> str:
        """Read the thinking summary narrator instruction prompt."""

        return self.prompt_path.read_text(encoding="utf-8")


ThinkingSummaryInput = ThinkingActivityInput
ThinkingSummaryResult = ThinkingActivityResult
ThinkingSummaryNarrator = ThinkingActivityNarrator


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


def _thinking_activity_input_payload(payload: ThinkingActivityInput) -> dict[str, Any]:
    """Build the strict public JSON input for the activity narrator."""

    return {
        "user_request": payload.user_request,
        "selected_model": payload.selected_model,
        "run_status": payload.run_status,
        "duration_ms": payload.duration_ms,
        "activity_facts": list(payload.activity_facts),
        "public_event_ids": [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
            }
            for event in payload.events
        ],
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


def _summary_activity_items(
    value: object,
    events: tuple[RunEventRecord, ...],
    facts: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    """Validate narrator activity items against public evidence."""

    if not isinstance(value, list):
        return []
    if not MIN_ACTIVITY_ITEMS <= len(value) <= MAX_ACTIVITY_ITEMS:
        return []
    items: list[dict[str, Any]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            return []
        item = _summary_activity_item(raw_item, events, facts)
        if item is None:
            return []
        items.append(item)
    return items


def _summary_activity_item(
    raw_item: dict[str, Any],
    events: tuple[RunEventRecord, ...],
    facts: tuple[dict[str, Any], ...],
) -> dict[str, Any] | None:
    """Return one sanitized narrator activity item."""

    title = str(raw_item.get("title") or "").strip()
    body = str(raw_item.get("body") or "").strip()
    kind = str(raw_item.get("kind") or "orientation").strip()
    if not title or not body:
        return None
    if kind not in ACTIVITY_KINDS:
        return None
    if _contains_full_url(f"{title}\n{body}"):
        return None
    if _contains_forbidden_reasoning_terms(f"{title}\n{body}"):
        return None
    if _contains_public_thinking_terms(f"{title}\n{body}"):
        return None
    if _contains_raw_activity_detail_terms(f"{title}\n{body}"):
        return None
    if _contains_boilerplate_activity_terms(f"{title}\n{body}"):
        return None
    evidence_fact_ids = _strict_fact_ids(raw_item.get("evidence_fact_ids"), facts)
    if not evidence_fact_ids:
        return None
    evidence_ids = _strict_fact_event_ids(
        raw_item.get("evidence_event_ids"),
        facts,
        evidence_fact_ids,
    )
    if not evidence_ids:
        return None
    if not _claims_have_fact_evidence(f"{title}\n{body}", facts, evidence_fact_ids):
        return None
    return {
        "id": f"act_{uuid4().hex}",
        "title": title[:MAX_ACTIVITY_TITLE_CHARS],
        "body": body[:MAX_ACTIVITY_BODY_CHARS],
        "status": "completed",
        "kind": kind,
        "source": "narrator_model",
        "evidence_fact_ids": evidence_fact_ids,
        "evidence_event_ids": evidence_ids,
        "confidence": _confidence(raw_item.get("confidence")),
    }


def _strict_evidence_ids(
    value: object,
    events: tuple[RunEventRecord, ...],
) -> list[str]:
    """Return evidence ids only when all supplied ids exist."""

    if not isinstance(value, list) or not value:
        return []
    known = {event.event_id for event in events}
    ids = [item for item in value if isinstance(item, str)]
    if len(ids) != len(value):
        return []
    if any(item not in known for item in ids):
        return []
    return ids


def _strict_fact_ids(
    value: object,
    facts: tuple[dict[str, Any], ...],
) -> list[str]:
    """Return fact ids only when all supplied ids exist."""

    if not isinstance(value, list) or not value:
        return []
    known = {fact.get("id") for fact in facts if isinstance(fact.get("id"), str)}
    ids = [item for item in value if isinstance(item, str)]
    if len(ids) != len(value):
        return []
    if any(item not in known for item in ids):
        return []
    return ids


def _strict_fact_event_ids(
    value: object,
    facts: tuple[dict[str, Any], ...],
    evidence_fact_ids: list[str],
) -> list[str]:
    """Return event ids that are cited by the selected facts."""

    fact_events: set[str] = set()
    for fact in facts:
        if fact.get("id") not in evidence_fact_ids:
            continue
        ids = fact.get("evidence_event_ids")
        if isinstance(ids, list):
            fact_events.update(item for item in ids if isinstance(item, str))
    if not isinstance(value, list) or not value:
        return sorted(fact_events)
    ids = [item for item in value if isinstance(item, str)]
    if len(ids) != len(value):
        return []
    if any(item not in fact_events for item in ids):
        return []
    return ids


def _aggregate_evidence_ids(items: list[dict[str, Any]]) -> list[str]:
    """Return stable unique evidence ids cited by activity items."""

    seen: set[str] = set()
    evidence_ids: list[str] = []
    for item in items:
        for evidence_id in item["evidence_event_ids"]:
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            evidence_ids.append(evidence_id)
    return evidence_ids


def _average_confidence(items: list[dict[str, Any]]) -> float:
    """Return the average confidence across validated activity items."""

    if not items:
        return 0.0
    total = sum(float(item.get("confidence") or 0.0) for item in items)
    return round(total / len(items), 4)


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


def _contains_public_thinking_terms(text: str) -> bool:
    """Return whether public activity text blurs into private thinking."""

    lowered = text.lower()
    forbidden = (
        "reasoning",
        "thinking",
        "thought process",
        "reasoning round",
        "llm reasoning",
        "model reasoning",
        "thinking process",
        "private thinking",
        "\u601d\u8003",
        "\u63a8\u7406",
        "\u601d\u7ef4\u94fe",
        "\u601d\u8003\u6d41\u7a0b",
        "\u63a8\u7406\u6d41\u7a0b",
        "\u63a8\u7406\u8f6e\u6b21",
        "\u6a21\u578b\u63a8\u7406",
        "\u601d\u8003\u8fc7\u7a0b",
    )
    return any(term in lowered for term in forbidden)

def _contains_full_url(text: str) -> bool:
    """Return whether visible summary text exposes a full URL."""

    return "http://" in text.lower() or "https://" in text.lower()


def _contains_raw_activity_detail_terms(text: str) -> bool:
    """Return whether text exposes raw tool-call detail wording."""

    lowered = text.lower()
    forbidden = (
        "query",
        "argument",
        "arguments",
        "raw args",
        "raw payload",
        "\u53c2\u6570",
        "\u67e5\u8be2\u8bcd",
        "\u641c\u7d22\u8bcd",
    )
    return any(term in lowered for term in forbidden)


def _contains_boilerplate_activity_terms(text: str) -> bool:
    """Return whether text is a generic lifecycle label, not real activity."""

    lowered = text.lower()
    forbidden = (
        "preparing the run",
        "reading the request",
        "writing the answer",
        "final response",
        "set up the runtime",
        "setting up the runtime",
        "model response received",
        "\u51c6\u5907\u8fd0\u884c",
        "\u51c6\u5907\u56de\u7b54",
        "\u6700\u7ec8\u56de\u7b54",
        "\u8bfb\u53d6\u8bf7\u6c42",
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


def _claims_have_fact_evidence(
    text: str,
    facts: tuple[dict[str, Any], ...],
    evidence_fact_ids: list[str],
) -> bool:
    """Reject visible action claims unsupported by selected facts."""

    selected = [
        fact for fact in facts if isinstance(fact.get("id"), str) and fact["id"] in evidence_fact_ids
    ]
    lowered = text.lower()
    checks = [
        (("understood", "request", "goal", "\u7406\u89e3", "\u8bf7\u6c42", "\u76ee\u6807"), {"request_orientation"}),
        (("search", "searched", "\u68c0\u7d22", "\u641c\u7d22"), {"web_search_result"}),
        (("read", "opened", "fetched", "\u8bfb\u53d6", "\u6253\u5f00"), {"web_fetch_result"}),
        (("image", "generated image", "\u751f\u6210\u56fe\u7247", "\u56fe\u50cf"), {"image_generation"}),
        (("tool", "\u5de5\u5177"), {"tool_call", "tool_result", "web_search_result", "web_fetch_result", "image_generation", "error"}),
        (("verify", "verified", "checked", "\u9a8c\u8bc1", "\u6838\u5bf9"), {"web_fetch_result", "web_search_result"}),
    ]
    kinds = {str(fact.get("kind") or "") for fact in selected}
    for terms, required_kinds in checks:
        if any(term in lowered for term in terms) and not kinds.intersection(required_kinds):
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
