"""Validate the unified task pool under ``data/tasks/task_pool.json``.

The validator checks:

* top-level JSON shape is a list;
* every task has exactly the unified schema fields;
* ``source`` is ``bfcl`` or ``toolbench``;
* ``available_tools`` contains only frozen tool names and no duplicates;
* ``expected_behavior.must_call`` and ``must_not_call`` reference only tools
  exposed in ``available_tools``;
* ``task_id`` is a non-empty string and unique;
* the eight task categories are present with the expected distribution.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

FROZEN_TOOL_NAMES: tuple[str, ...] = (
    "web_search",
    "web_fetch",
    "memory_search",
    "current_time",
    "evidence_submit",
    "update_activity",
    "skills_list",
    "skill_view",
)

TASK_CATEGORIES: tuple[str, ...] = (
    "single_tool",
    "multi_tool",
    "sequential",
    "argument_constraint",
    "failure_retry",
    "multi_turn",
    "no_tool",
    "evidence_synthesis",
)

EXPECTED_COUNTS: dict[str, int] = {
    "single_tool": 250,
    "multi_tool": 250,
    "sequential": 250,
    "argument_constraint": 200,
    "failure_retry": 150,
    "multi_turn": 150,
    "no_tool": 100,
    "evidence_synthesis": 100,
}

UNIFIED_KEYS = frozenset({"task_id", "source", "instruction", "available_tools", "expected_behavior"})
BEHAVIOR_KEYS = frozenset({"must_call", "must_not_call", "success_condition"})

_CATEGORY_RE = re.compile(
    r"_(single_tool|multi_tool|sequential|argument_constraint|failure_retry|multi_turn|no_tool|evidence_synthesis)_\d+$"
)


def default_pool_path() -> Path:
    """Return the repository-root task-pool path regardless of cwd."""

    return Path(__file__).resolve().parents[3] / "data" / "tasks" / "task_pool.json"


def _error(errors: list[str], index: int, message: str) -> None:
    errors.append(f"task[{index}]: {message}")


def _validate_task(task: Any, index: int, errors: list[str]) -> None:
    if not isinstance(task, dict):
        _error(errors, index, "task must be a JSON object")
        return

    top_keys = set(task.keys())
    if top_keys != UNIFIED_KEYS:
        _error(
            errors,
            index,
            f"top-level keys invalid; missing={sorted(UNIFIED_KEYS - top_keys)} extra={sorted(top_keys - UNIFIED_KEYS)}",
        )

    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        _error(errors, index, "task_id must be a non-empty string")

    source = task.get("source")
    if source not in {"bfcl", "toolbench"}:
        _error(errors, index, "source must be 'bfcl' or 'toolbench'")

    instruction = task.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        _error(errors, index, "instruction must be a non-empty string")

    available_tools = task.get("available_tools")
    if not isinstance(available_tools, list) or not all(isinstance(tool, str) for tool in available_tools):
        _error(errors, index, "available_tools must be an array of strings")
    else:
        unknown = [tool for tool in available_tools if tool not in FROZEN_TOOL_NAMES]
        if unknown:
            _error(errors, index, f"available_tools contains non-frozen tools: {unknown}")
        if len(available_tools) != len(set(available_tools)):
            _error(errors, index, "available_tools contains duplicates")

    behavior = task.get("expected_behavior")
    if not isinstance(behavior, dict):
        _error(errors, index, "expected_behavior must be a JSON object")
        return
    behavior_keys = set(behavior.keys())
    if behavior_keys != BEHAVIOR_KEYS:
        _error(
            errors,
            index,
            f"expected_behavior keys invalid; missing={sorted(BEHAVIOR_KEYS - behavior_keys)} extra={sorted(behavior_keys - BEHAVIOR_KEYS)}",
        )

    must_call = behavior.get("must_call")
    must_not_call = behavior.get("must_not_call")
    success_condition = behavior.get("success_condition")

    if not isinstance(must_call, list) or not all(isinstance(tool, str) for tool in must_call):
        _error(errors, index, "must_call must be an array of strings")
    if not isinstance(must_not_call, list) or not all(isinstance(tool, str) for tool in must_not_call):
        _error(errors, index, "must_not_call must be an array of strings")
    if not isinstance(success_condition, str) or not success_condition.strip():
        _error(errors, index, "success_condition must be a non-empty string")

    if isinstance(available_tools, list) and isinstance(must_call, list):
        missing = [tool for tool in must_call if tool not in available_tools]
        if missing:
            _error(errors, index, f"must_call references tools not exposed by available_tools: {missing}")
        if len(must_call) != len(set(must_call)):
            _error(errors, index, "must_call contains duplicates")
    if isinstance(available_tools, list) and isinstance(must_not_call, list):
        missing = [tool for tool in must_not_call if tool not in available_tools]
        if missing:
            _error(errors, index, f"must_not_call references tools not exposed by available_tools: {missing}")
        if len(must_not_call) != len(set(must_not_call)):
            _error(errors, index, "must_not_call contains duplicates")

    overlap = set(must_call or []) & set(must_not_call or [])
    if overlap:
        _error(errors, index, f"tool appears in both must_call and must_not_call: {sorted(overlap)}")


def _infer_category(task: dict[str, Any]) -> str:
    """Infer the category from ``task_id``, with a behavior-based fallback."""

    task_id = str(task.get("task_id") or "")
    match = _CATEGORY_RE.search(task_id)
    if match:
        return match.group(1)

    behavior = task.get("expected_behavior") or {}
    must_call = list(behavior.get("must_call") or [])
    instruction = str(task.get("instruction") or "")
    available = list(task.get("available_tools") or [])

    if not must_call:
        return "no_tool"
    if "evidence_submit" in must_call and any(tool in must_call for tool in ("web_search", "web_fetch")):
        return "evidence_synthesis"
    if "[TURN" in instruction:
        return "multi_turn"
    if len(must_call) > 1:
        return "sequential" if "web_fetch" in must_call else "multi_tool"
    if available and available[0] in must_call and len(available) > 1:
        return "single_tool"
    return "single_tool"


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"{path}: top-level JSON must be a list")
    if not data:
        raise ValueError(f"{path}: task pool must not be empty")
    return data


def _print_distribution(label: str, counts: Counter[str], total: int) -> None:
    print(label)
    for key in sorted(counts.keys()):
        count = counts[key]
        print(f"  {key}: {count} ({count / total * 100:.1f}%)")


def validate_pool(path: Path) -> int:
    tasks = _load_tasks(path)
    errors: list[str] = []

    for index, task in enumerate(tasks):
        _validate_task(task, index, errors)

    task_ids = [str(task.get("task_id") or "") for task in tasks if isinstance(task, dict)]
    duplicate_ids = [task_id for task_id, count in Counter(task_ids).items() if count > 1]
    if duplicate_ids:
        errors.append(f"duplicate task_id values: {duplicate_ids[:20]}")

    if errors:
        print(f"Task pool validation FAILED with {len(errors)} error(s):")
        for error in errors[:100]:
            print(f"  - {error}")
        if len(errors) > 100:
            print(f"  ... and {len(errors) - 100} more")
        return 1

    total = len(tasks)
    source_counts = Counter(str(task["source"]) for task in tasks)
    category_counts = Counter(_infer_category(task) for task in tasks)

    print(f"Task pool validation passed: {total} tasks\n")
    _print_distribution("source distribution:", source_counts, total)
    print()
    _print_distribution("category distribution:", category_counts, total)

    print()
    for category in TASK_CATEGORIES:
        expected = EXPECTED_COUNTS[category]
        actual = category_counts.get(category, 0)
        status = "OK" if actual == expected else f"MISMATCH expected={expected}"
        print(f"  {category}: actual={actual} expected={expected} [{status}]")

    mismatches = [
        category
        for category in TASK_CATEGORIES
        if category_counts.get(category, 0) != EXPECTED_COUNTS[category]
    ]
    if not 1200 <= total <= 1600:
        print(f"WARNING: total {total} is outside the requested 1200-1600 range.")
    if mismatches:
        print(f"WARNING: category count mismatch for {mismatches}.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=None, help="path to task_pool.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = args.path or default_pool_path()
    if not path.exists():
        print(f"task pool not found: {path}")
        return 2
    return validate_pool(path)


if __name__ == "__main__":
    raise SystemExit(main())
