"""Versioned, redacted, and deterministically serialized trajectories."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


TRAJECTORY_SCHEMA_VERSION = "klara.trajectory.v1"

_FORBIDDEN_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "chain_of_thought",
    "hidden_reasoning",
    "private_payload",
    "raw_prompt",
    "reasoning_content",
}
_FORBIDDEN_VALUES = (
    re.compile(r"\bbearer\s+[a-z0-9._-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[a-z0-9_-]{12,}", re.IGNORECASE),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
)


def canonical_json(value: Any) -> str:
    """Return the canonical JSON representation used by dataset hashes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_sha256(value: str | bytes) -> str:
    """Hash canonical text or bytes with SHA-256."""

    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class TrajectoryEvent:
    """One public state/action/observation/policy/outcome event."""

    event_id: str
    run_id: str
    seq: int
    type: str
    turn_index: int
    state: str
    action: str = ""
    observation: str = ""
    policy_decision: str = ""
    outcome: str = ""
    tool_call_id: str | None = None
    source_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    metrics: dict[str, float | int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate fields that do not require run-level context."""

        for label, value in (
            ("event_id", self.event_id),
            ("run_id", self.run_id),
            ("type", self.type),
            ("state", self.state),
        ):
            if not value.strip():
                raise ValueError(f"trajectory {label} must not be empty")
        if self.seq < 1:
            raise ValueError("trajectory seq must be positive")
        if self.turn_index < 0:
            raise ValueError("trajectory turn_index must not be negative")

    @property
    def turn_id(self) -> str:
        """Return the stable run-local identity derived from the core turn index."""

        return f"{self.run_id}:turn:{self.turn_index}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize one redacted event."""

        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "seq": self.seq,
            "type": self.type,
            "turn_index": self.turn_index,
            "turn_id": self.turn_id,
            "state": self.state,
            "action": self.action,
            "observation": self.observation,
            "policy_decision": self.policy_decision,
            "outcome": self.outcome,
            "tool_call_id": self.tool_call_id,
            "source_ids": list(self.source_ids),
            "claim_ids": list(self.claim_ids),
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TrajectoryEvent":
        """Parse one event from the exact public schema."""

        required = {"event_id", "run_id", "seq", "type", "turn_index", "state"}
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(f"trajectory event missing fields: {missing}")
        expected_turn_id = f"{raw['run_id']}:turn:{int(raw['turn_index'])}"
        if raw.get("turn_id", expected_turn_id) != expected_turn_id:
            raise ValueError("trajectory turn_id does not match run_id and turn_index")
        return cls(
            event_id=str(raw["event_id"]),
            run_id=str(raw["run_id"]),
            seq=int(raw["seq"]),
            type=str(raw["type"]),
            turn_index=int(raw["turn_index"]),
            state=str(raw["state"]),
            action=str(raw.get("action", "")),
            observation=str(raw.get("observation", "")),
            policy_decision=str(raw.get("policy_decision", "")),
            outcome=str(raw.get("outcome", "")),
            tool_call_id=(
                str(raw["tool_call_id"])
                if raw.get("tool_call_id") is not None
                else None
            ),
            source_ids=tuple(str(value) for value in raw.get("source_ids", [])),
            claim_ids=tuple(str(value) for value in raw.get("claim_ids", [])),
            metrics={
                str(key): value for key, value in dict(raw.get("metrics", {})).items()
            },
        )


@dataclass(frozen=True)
class TrajectoryRecord:
    """One complete public run with declared join-key domains."""

    run_id: str
    events: tuple[TrajectoryEvent, ...]
    source_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    schema_version: str = TRAJECTORY_SCHEMA_VERSION
    split: str = "train"
    lineage_id: str = ""

    def __post_init__(self) -> None:
        """Validate the complete run, including every relationship."""

        if self.schema_version != TRAJECTORY_SCHEMA_VERSION:
            raise ValueError(f"unsupported trajectory schema: {self.schema_version}")
        if not self.run_id.strip():
            raise ValueError("trajectory run_id must not be empty")
        if self.split not in {"train", "validation", "test"}:
            raise ValueError(f"unsupported trajectory split: {self.split}")
        self.validate()

    def validate(self) -> None:
        """Enforce ordering plus run, event, tool, source, and claim linkage."""

        if not self.events:
            raise ValueError(f"trajectory {self.run_id} has no events")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError(f"trajectory {self.run_id} has duplicate event ids")
        seqs = [event.seq for event in self.events]
        if seqs != list(range(1, len(self.events) + 1)):
            raise ValueError(f"trajectory {self.run_id} seq values are not contiguous")
        if any(event.run_id != self.run_id for event in self.events):
            raise ValueError(f"trajectory {self.run_id} contains a foreign run id")
        turns = [event.turn_index for event in self.events]
        if turns != sorted(turns):
            raise ValueError(f"trajectory {self.run_id} turn order is not monotonic")
        _require_unique(self.source_ids, "source ids")
        _require_unique(self.claim_ids, "claim ids")

        declared_sources = set(self.source_ids)
        declared_claims = set(self.claim_ids)
        started_tools: set[str] = set()
        terminal_tools: set[str] = set()
        for event in self.events:
            unknown_sources = set(event.source_ids) - declared_sources
            unknown_claims = set(event.claim_ids) - declared_claims
            if unknown_sources:
                raise ValueError(f"unknown source ids: {sorted(unknown_sources)}")
            if unknown_claims:
                raise ValueError(f"unknown claim ids: {sorted(unknown_claims)}")
            if event.type == "tool.started":
                if not event.tool_call_id:
                    raise ValueError("tool.started requires tool_call_id")
                if event.tool_call_id in started_tools:
                    raise ValueError(f"duplicate tool start: {event.tool_call_id}")
                started_tools.add(event.tool_call_id)
            if event.type in {"tool.completed", "tool.failed"}:
                if not event.tool_call_id:
                    raise ValueError(f"{event.type} requires tool_call_id")
                if event.tool_call_id not in started_tools:
                    raise ValueError(f"tool terminal without start: {event.tool_call_id}")
                if event.tool_call_id in terminal_tools:
                    raise ValueError(f"duplicate tool terminal: {event.tool_call_id}")
                terminal_tools.add(event.tool_call_id)
        if terminal_tools != started_tools:
            missing = sorted(started_tools - terminal_tools)
            raise ValueError(f"tool calls missing terminal events: {missing}")

        findings = leakage_findings(self.to_dict())
        if findings:
            raise ValueError("trajectory contains private or secret data: " + "; ".join(findings))

    def linkage_counts(self) -> tuple[int, int]:
        """Return passed and total atomic ID-linkage checks for reports."""

        total = 0
        passed = 0
        for event in self.events:
            total += 3
            passed += int(event.run_id == self.run_id)
            passed += int(bool(event.event_id))
            passed += int(event.seq >= 1)
            for source_id in event.source_ids:
                total += 1
                passed += int(source_id in self.source_ids)
            for claim_id in event.claim_ids:
                total += 1
                passed += int(claim_id in self.claim_ids)
            if event.tool_call_id:
                total += 1
                terminal_ids = {
                    item.tool_call_id
                    for item in self.events
                    if item.type in {"tool.completed", "tool.failed"}
                }
                started_ids = {
                    item.tool_call_id
                    for item in self.events
                    if item.type == "tool.started"
                }
                passed += int(
                    event.tool_call_id in started_ids
                    and event.tool_call_id in terminal_ids
                )
        total += len(self.events)
        passed += sum(
            event.turn_id == f"{self.run_id}:turn:{event.turn_index}"
            and (index == 0 or event.turn_index >= self.events[index - 1].turn_index)
            for index, event in enumerate(self.events)
        )
        return passed, total

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete versioned record."""

        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "split": self.split,
            "lineage_id": self.lineage_id,
            "source_ids": list(self.source_ids),
            "claim_ids": list(self.claim_ids),
            "events": [event.to_dict() for event in self.events],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TrajectoryRecord":
        """Parse and validate one versioned trajectory record."""

        required = {"schema_version", "run_id", "events", "source_ids", "claim_ids"}
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(f"trajectory record missing fields: {missing}")
        raw_events = raw["events"]
        if not isinstance(raw_events, list):
            raise ValueError("trajectory events must be a list")
        return cls(
            schema_version=str(raw["schema_version"]),
            run_id=str(raw["run_id"]),
            split=str(raw.get("split", "train")),
            lineage_id=str(raw.get("lineage_id", "")),
            source_ids=tuple(str(value) for value in raw["source_ids"]),
            claim_ids=tuple(str(value) for value in raw["claim_ids"]),
            events=tuple(TrajectoryEvent.from_dict(event) for event in raw_events),
        )


def export_jsonl(records: Iterable[TrajectoryRecord], path: Path) -> str:
    """Write canonical JSONL in stable run-id order and return its hash."""

    ordered = sorted(records, key=lambda record: record.run_id)
    text = "".join(canonical_json(record.to_dict()) + "\n" for record in ordered)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return stable_sha256(text)


def load_jsonl(path: Path) -> tuple[TrajectoryRecord, ...]:
    """Load and validate every non-empty canonical trajectory line."""

    records: list[TrajectoryRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError("record must be a JSON object")
            records.append(TrajectoryRecord.from_dict(raw))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid trajectory line {line_number}: {exc}") from exc
    if not records:
        raise ValueError("trajectory dataset must contain at least one record")
    run_ids = [record.run_id for record in records]
    _require_unique(run_ids, "run ids")
    return tuple(records)


def project_public_events(
    events: Iterable[Any],
    *,
    split: str = "train",
    lineage_id: str = "",
) -> TrajectoryRecord:
    """Project core public events into the training-safe trajectory schema.

    Raw prompts, final answer text, tool arguments/results, public reasoning
    summaries, and private references are intentionally not copied. The
    projection retains lifecycle state, tool identity/linkage, bounded outcome
    labels, IDs, and numeric usage/latency observations.
    """

    raw_events: list[dict[str, Any]] = []
    for event in events:
        raw = event.to_public_dict() if hasattr(event, "to_public_dict") else event
        if not isinstance(raw, dict):
            raise ValueError("public event must be a dictionary or KlaraEvent")
        raw_events.append(raw)
    if not raw_events:
        raise ValueError("public event projection requires at least one event")

    run_id = str(raw_events[0].get("run_id", ""))
    current_turn = 0
    projected: list[TrajectoryEvent] = []
    declared_sources: set[str] = set()
    declared_claims: set[str] = set()
    for raw in raw_events:
        payload = raw.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        if "turn_index" in payload:
            current_turn = int(payload["turn_index"])
        event_type = str(raw.get("type", ""))
        tool_call_id, tool_name = _public_tool_identity(payload)
        source_ids = _public_ids(payload, "source_id", "source_ids")
        claim_ids = _public_ids(payload, "claim_id", "claim_ids")
        declared_sources.update(source_ids)
        declared_claims.update(claim_ids)
        projected.append(
            TrajectoryEvent(
                event_id=str(raw.get("event_id", "")),
                run_id=str(raw.get("run_id", "")),
                seq=int(raw.get("seq", 0)),
                type=event_type,
                turn_index=current_turn,
                state=_state_for_event(event_type),
                action=tool_name if event_type.endswith("started") else "",
                observation=_public_outcome(event_type, payload),
                policy_decision=_public_policy(payload),
                outcome=_public_outcome(event_type, payload),
                tool_call_id=tool_call_id,
                source_ids=source_ids,
                claim_ids=claim_ids,
                metrics=_numeric_metrics(payload),
            )
        )
    return TrajectoryRecord(
        run_id=run_id,
        events=tuple(projected),
        source_ids=tuple(sorted(declared_sources)),
        claim_ids=tuple(sorted(declared_claims)),
        split=split,
        lineage_id=lineage_id,
    )


def leakage_findings(value: Any, path: str = "$") -> list[str]:
    """Return paths containing known secret or hidden-reasoning material."""

    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower().replace("-", "_")
            child_path = f"{path}.{key}"
            if key_text in _FORBIDDEN_KEYS:
                findings.append(child_path)
            findings.extend(leakage_findings(item, child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            findings.extend(leakage_findings(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in _FORBIDDEN_VALUES):
            findings.append(path)
    return findings


def _public_tool_identity(payload: dict[str, Any]) -> tuple[str | None, str]:
    """Extract only stable tool identity, never arguments or result content."""

    call = payload.get("tool_call")
    if isinstance(call, dict):
        call_id = str(call.get("id", "")) or None
        return call_id, str(call.get("name", ""))
    result = payload.get("tool_result")
    if isinstance(result, dict):
        call_id = str(result.get("tool_call_id", "")) or None
        return call_id, str(result.get("name", ""))
    return None, ""


def _public_ids(
    payload: dict[str, Any],
    singular_key: str,
    plural_key: str,
) -> tuple[str, ...]:
    """Collect explicit top-level public IDs without scanning arbitrary text."""

    values: set[str] = set()
    singular = payload.get(singular_key)
    if isinstance(singular, str) and singular:
        values.add(singular)
    plural = payload.get(plural_key)
    if isinstance(plural, list):
        values.update(str(value) for value in plural if str(value))
    return tuple(sorted(values))


def _state_for_event(event_type: str) -> str:
    """Map lifecycle names to a small reusable trajectory state vocabulary."""

    if event_type.startswith("run."):
        return "completed" if event_type != "run.started" else "started"
    if event_type.startswith("tool.") or event_type.startswith("pre_tool_use"):
        return "tool_use"
    if event_type.startswith("post_tool_use"):
        return "observing"
    if event_type.startswith("evidence."):
        return "verifying"
    if event_type.startswith("stop."):
        return "stopping"
    return "reasoning_boundary"


def _public_policy(payload: dict[str, Any]) -> str:
    """Retain a finite allow/block label while dropping free-form reasons."""

    allowed = payload.get("allowed")
    if isinstance(allowed, bool):
        return "allow" if allowed else "block"
    return ""


def _public_outcome(event_type: str, payload: dict[str, Any]) -> str:
    """Return a bounded lifecycle outcome without copying observation text."""

    if event_type == "tool.completed":
        return "success"
    if event_type == "tool.failed":
        return "failed"
    if event_type == "run.completed":
        return "completed"
    if event_type == "run.failed":
        return "failed"
    status = payload.get("status")
    return str(status) if isinstance(status, str) and len(status) <= 48 else ""


def _numeric_metrics(payload: dict[str, Any]) -> dict[str, float | int]:
    """Flatten approved numeric latency, token, and cost measurements."""

    approved = {
        "duration_ms",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
    }
    result: dict[str, float | int] = {}
    for container_key in ("metrics", "usage"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        for key, value in container.items():
            if key in approved and isinstance(value, (int, float)) and not isinstance(value, bool):
                result[str(key)] = value
    return result


def _require_unique(values: Iterable[str], label: str) -> None:
    """Raise when a sequence contains duplicate stable identifiers."""

    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"trajectory has duplicate {label}")
