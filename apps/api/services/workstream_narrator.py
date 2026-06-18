from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from apps.api.schemas import RunEventRecord
from klara.core.loop import LlmClient
from klara.core.messages import KlaraMessage

MAX_NOTE_CHARS = 180


@dataclass(frozen=True)
class WorkstreamNarratorInput:
    """Public runtime state available to the optional narrator."""

    user_request: str
    selected_model: str
    run_status: str
    phase: str
    elapsed_ms: int
    recent_events: tuple[RunEventRecord, ...]
    previous_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkstreamNote:
    """Validated narrator note ready for RunEvent persistence."""

    text: str
    evidence_event_ids: tuple[str, ...]
    confidence: float


class WorkstreamNarrator:
    """Generate short evidence-bound notes from public run events."""

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
                    content=json.dumps(_input_payload(payload), ensure_ascii=False),
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
        evidence_ids = _valid_evidence_ids(raw.get("evidence_event_ids"), payload)
        if not evidence_ids:
            return None
        confidence = raw.get("confidence")
        if not isinstance(confidence, int | float) or isinstance(confidence, bool):
            confidence = 0.0
        return WorkstreamNote(
            text=text[:MAX_NOTE_CHARS],
            evidence_event_ids=tuple(evidence_ids),
            confidence=max(0.0, min(float(confidence), 1.0)),
        )

    def _prompt(self) -> str:
        """Read the narrator instruction prompt."""

        return self.prompt_path.read_text(encoding="utf-8")


def _input_payload(payload: WorkstreamNarratorInput) -> dict[str, Any]:
    """Build the strict public JSON input for the narrator model."""

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
            return f"tool result: {name}, ok={ok}"
    return event.message[:160]


def _valid_evidence_ids(value: object, payload: WorkstreamNarratorInput) -> list[str]:
    """Filter evidence ids to ids that exist in recent public events."""

    if not isinstance(value, list):
        return []
    known = {event.event_id for event in payload.recent_events}
    return [item for item in value if isinstance(item, str) and item in known]


def _contains_forbidden_reasoning_terms(text: str) -> bool:
    """Return whether the note exposes or imitates hidden reasoning."""

    lowered = text.lower()
    forbidden = (
        "chain-of-thought",
        "chain of thought",
        "scratchpad",
        "hidden reasoning",
        "raw reasoning",
        "i realized",
        "i inferred",
        "我意识到",
        "我推理",
    )
    return any(term in lowered for term in forbidden)


def _claims_have_evidence(text: str, events: tuple[RunEventRecord, ...]) -> bool:
    """Reject action claims that are unsupported by recent public events."""

    lowered = text.lower()
    checks = [
        (("search", "searched", "搜索", "检索"), _has_search_event),
        (("read", "opened", "fetched", "读取", "打开"), _has_read_event),
        (("edit", "edited", "modify", "modified", "修改", "编辑"), _has_edit_event),
        (("verify", "verified", "test", "tested", "验证", "测试"), _has_verify_event),
        (("tool", "called", "调用工具"), _has_tool_event),
    ]
    for terms, predicate in checks:
        if any(term in lowered for term in terms) and not predicate(events):
            return False
    return True


def _has_tool_event(events: tuple[RunEventRecord, ...]) -> bool:
    return any(event.event_type.startswith("tool_call_") for event in events)


def _has_search_event(events: tuple[RunEventRecord, ...]) -> bool:
    return any(_event_mentions(event, ("search", "web_search", "搜索")) for event in events)


def _has_read_event(events: tuple[RunEventRecord, ...]) -> bool:
    return any(_event_mentions(event, ("read", "fetch", "open", "web_fetch", "读取", "打开")) for event in events)


def _has_edit_event(events: tuple[RunEventRecord, ...]) -> bool:
    return any(_event_mentions(event, ("edit", "modify", "write", "修改", "编辑")) for event in events)


def _has_verify_event(events: tuple[RunEventRecord, ...]) -> bool:
    return any(_event_mentions(event, ("verify", "test", "check", "验证", "测试")) for event in events)


def _event_mentions(event: RunEventRecord, needles: tuple[str, ...]) -> bool:
    text = json.dumps(
        {"event_type": event.event_type, "message": event.message, "payload": event.payload},
        ensure_ascii=False,
    ).lower()
    return any(needle in text for needle in needles)
