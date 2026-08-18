"""Deterministic trajectory filter for teacher rollouts.

Reads ``data/trajectories/raw.jsonl`` and writes ``data/trajectories/clean.jsonl``.
The filter is intentionally deterministic and performs exactly the checks needed
by the frozen eval contract:

* every line is valid JSON and a JSON object
* every tool call is one of the eight frozen tools
* every tool-call argument object validates against the frozen schema
* no duplicate/cyclic dead-loop tool-call sequence is present
* the final answer satisfies the task's ``expected_behavior``
* duplicate trajectories sharing the same template are removed
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate as jsonschema_validate

from klara.eval.teacher_rollout import TOOL_NAMES, TOOL_SCHEMAS


FILTER_SCHEMA_VERSION = "klara.trajectory-filter.v1"
DEFAULT_RAW_PATH = Path("data/trajectories/raw.jsonl")
DEFAULT_CLEAN_PATH = Path("data/trajectories/clean.jsonl")


def canonical_json(value: Any) -> str:
    """Return stable JSON text used for fingerprints and signatures."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_text(value: Any) -> str:
    """Normalize free text for behavior checks without mutating the record."""

    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def _call_signature(call: dict[str, Any]) -> str:
    name = str(call.get("name", ""))
    arguments = call.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}
    return f"{name}:{canonical_json(arguments)}"


def _used_tool_names(tool_calls: list[dict[str, Any]]) -> list[str]:
    return [str(call.get("name", "")) for call in tool_calls]


def _expected_behavior(record: dict[str, Any]) -> dict[str, Any]:
    behavior = record.get("expected_behavior")
    if isinstance(behavior, dict):
        return behavior
    task = record.get("task")
    if isinstance(task, dict):
        behavior = task.get("expected_behavior")
        if isinstance(behavior, dict):
            return behavior
    return {}


def _validate_json_line(line: str) -> tuple[dict[str, Any] | None, str | None]:
    if not line.strip():
        return None, "empty_line"
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        return None, f"invalid_json:{exc}"
    if not isinstance(raw, dict):
        return None, "not_json_object"
    return raw, None


def validate_record(record: dict[str, Any]) -> list[str]:
    """Return a list of deterministic rejection reasons (empty means pass)."""

    reasons: list[str] = []

    schema_version = str(record.get("schema_version", ""))
    if schema_version not in {"", "klara.teacher-rollout.v1"}:
        reasons.append(f"unsupported_schema:{schema_version}")

    task_id = str(record.get("task_id", "")).strip()
    if not task_id:
        reasons.append("missing_task_id")

    tool_calls = record.get("tool_calls")
    if not isinstance(tool_calls, list):
        reasons.append("missing_tool_calls")
        return reasons
    if not tool_calls:
        reasons.append("no_tool_calls")

    call_ids: list[str] = []
    signatures: list[str] = []
    signature_counts: dict[str, int] = {}
    task = record.get("task", {})
    if isinstance(task, dict):
        allowed_tools = task.get("available_tools", [])
    else:
        allowed_tools = []
    if isinstance(allowed_tools, list) and allowed_tools:
        allowed_set = set(str(name) for name in allowed_tools)
    else:
        allowed_set = set(TOOL_NAMES)

    for index, call in enumerate(tool_calls):
        prefix = f"tool[{index}]"
        if not isinstance(call, dict):
            reasons.append(f"{prefix}:not_object")
            continue
        name = str(call.get("name", ""))
        arguments = call.get("arguments", {})
        if not name:
            reasons.append(f"{prefix}:missing_name")
        elif name not in TOOL_NAMES:
            reasons.append(f"{prefix}:unknown_tool:{name}")
        elif name not in allowed_set:
            reasons.append(f"{prefix}:tool_not_in_task:{name}")
        if name in TOOL_NAMES:
            if not isinstance(arguments, dict):
                reasons.append(f"{prefix}:arguments_not_object")
            else:
                try:
                    jsonschema_validate(instance=arguments, schema=TOOL_SCHEMAS[name])
                except ValidationError as exc:
                    path = ".".join(str(part) for part in exc.absolute_path)
                    reasons.append(f"{prefix}:schema:{name}:{path or '<root>'}:{exc.message}")
        call_id = str(call.get("call_id", "")).strip()
        if call_id:
            call_ids.append(call_id)
        if name:
            signature = _call_signature(call)
            signatures.append(signature)
            signature_counts[signature] = signature_counts.get(signature, 0) + 1

    if len(call_ids) != len(set(call_ids)):
        reasons.append("duplicate_call_ids")

    # Dead-loop detection: same tool name + exact arguments repeated more than
    # twice is never useful and indicates a stuck deterministic loop.
    for signature, count in signature_counts.items():
        if count > 2:
            reasons.append(f"repeated_tool_call:{signature}")

    behavior = _expected_behavior(record)
    final_answer = str(record.get("final_answer", "")).strip()
    if behavior.get("final_answer_required", True) and not final_answer:
        reasons.append("empty_final_answer")

    normalized_final = normalize_text(final_answer)
    required_contains = behavior.get("final_answer_contains", [])
    if isinstance(required_contains, list):
        for needle in required_contains:
            if normalize_text(needle) not in normalized_final:
                reasons.append(f"final_answer_missing:{needle}")
    forbidden_contains = behavior.get("final_answer_not_contains", [])
    if isinstance(forbidden_contains, list):
        for needle in forbidden_contains:
            if normalize_text(needle) in normalized_final:
                reasons.append(f"final_answer_forbidden:{needle}")

    used_names = _used_tool_names(tool_calls)
    required_tools = behavior.get("required_tools", [])
    if isinstance(required_tools, list):
        for tool_name in required_tools:
            if tool_name not in used_names:
                reasons.append(f"required_tool_missing:{tool_name}")
    forbidden_tools = behavior.get("forbidden_tools", [])
    if isinstance(forbidden_tools, list):
        for tool_name in forbidden_tools:
            if tool_name in used_names:
                reasons.append(f"forbidden_tool_used:{tool_name}")

    if isinstance(behavior.get("min_tool_calls"), int):
        if len(tool_calls) < int(behavior["min_tool_calls"]):
            reasons.append("too_few_tool_calls")
    if isinstance(behavior.get("max_tool_calls"), int):
        if len(tool_calls) > int(behavior["max_tool_calls"]):
            reasons.append("too_many_tool_calls")

    if behavior.get("require_evidence_submit") and "evidence_submit" not in used_names:
        reasons.append("evidence_submit_required")

    return reasons


def template_key(record: dict[str, Any]) -> str:
    """Return a deterministic template fingerprint for de-duplication.

    The fingerprint uses task identity, the ordered tool-name sequence, and the
    normalized final answer.  It intentionally ignores rollout index, latency,
    exact token counts, and minor whitespace differences.
    """

    task_id = str(record.get("task_id", "")).strip()
    tool_calls = record.get("tool_calls", [])
    names = tuple(str(call.get("name", "")) for call in tool_calls if isinstance(call, dict))
    final_answer = normalize_text(record.get("final_answer", ""))
    payload = {"task_id": task_id, "tool_names": list(names), "final_answer": final_answer}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def filter_lines(raw_lines: list[str]) -> dict[str, Any]:
    """Deterministically filter raw JSONL lines into clean JSON objects."""

    clean: list[dict[str, Any]] = []
    seen_templates: set[str] = set()
    summary = {
        "raw_lines": 0,
        "empty_lines": 0,
        "invalid_json": 0,
        "rejected_checks": 0,
        "duplicates": 0,
        "clean": 0,
        "reasons": {},
    }

    for line in raw_lines:
        summary["raw_lines"] += 1
        record, error = _validate_json_line(line)
        if record is None:
            if error == "empty_line":
                summary["empty_lines"] += 1
            else:
                summary["invalid_json"] += 1
                summary["reasons"][error] = summary["reasons"].get(error, 0) + 1
            continue

        reasons = validate_record(record)
        if reasons:
            summary["rejected_checks"] += 1
            for reason in reasons:
                summary["reasons"][reason] = summary["reasons"].get(reason, 0) + 1
            continue

        key = template_key(record)
        if key in seen_templates:
            summary["duplicates"] += 1
            continue
        seen_templates.add(key)

        filtered_record = dict(record)
        filtered_record["filter"] = {
            "schema_version": FILTER_SCHEMA_VERSION,
            "passed": True,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "template_key": key,
            "tool_count": len(record.get("tool_calls", [])),
        }
        clean.append(filtered_record)
        summary["clean"] += 1

    return {"summary": summary, "clean": clean}


def load_raw_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"raw trajectory file not found: {path}")
    return path.read_text(encoding="utf-8").splitlines()


def write_clean(path: Path, clean: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in clean:
            handle.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter teacher trajectories deterministically")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_PATH)
    parser.add_argument("--clean", type=Path, default=DEFAULT_CLEAN_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw_lines = load_raw_lines(args.raw)
    result = filter_lines(raw_lines)
    write_clean(args.clean, result["clean"])
    summary = result["summary"]
    print(
        "filter_trajectories: "
        f"raw_lines={summary['raw_lines']} clean={summary['clean']} "
        f"invalid_json={summary['invalid_json']} rejected_checks={summary['rejected_checks']} "
        f"duplicates={summary['duplicates']} empty_lines={summary['empty_lines']}"
    )
    for reason, count in sorted(summary["reasons"].items(), key=lambda item: (-item[1], item[0]))[:20]:
        print(f"filter_trajectories: reason {reason}={count}")
    return 0 if summary["clean"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
