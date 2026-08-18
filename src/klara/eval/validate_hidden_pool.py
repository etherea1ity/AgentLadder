"""Validate the disjoint hidden/dev task pool.

The validator checks:

* top-level JSON shape is a list with exactly 1000 tasks;
* every task has the unified schema fields plus ``split``;
* ``split`` is ``dev`` for the first 200 tasks and ``hidden`` for the last 800;
* ``available_tools``, ``must_call``, and ``must_not_call`` contain only the
  eight frozen tools and contain no duplicates;
* ``task_id`` is a non-empty string and is unique inside the pool;
* the pool is fully disjoint from ``data/tasks/task_pool.json`` by both
  ``task_id`` and ``instruction`` (and by task-id prefix).
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

HIDDEN_POOL_KEYS = frozenset(
    {"task_id", "source", "instruction", "available_tools", "expected_behavior", "split"}
)
BEHAVIOR_KEYS = frozenset({"must_call", "must_not_call", "success_condition"})

_CATEGORY_RE = re.compile(
    r"_(single_tool|multi_tool|sequential|argument_constraint|failure_retry|multi_turn|no_tool|evidence_synthesis)_\d+$"
)

EXPECTED_TOTAL = 1000
EXPECTED_DEV = 200
EXPECTED_HIDDEN = 800


def default_hidden_path() -> Path:
    """Return the repository-root hidden/dev pool path regardless of cwd."""

    return Path(__file__).resolve().parents[3] / "data" / "tasks" / "hidden_dev_pool.json"


def default_train_path() -> Path:
    """Return the repository-root training pool path regardless of cwd."""

    return Path(__file__).resolve().parents[3] / "data" / "tasks" / "task_pool.json"


def _error(errors: list[str], index: int, message: str) -> None:
    errors.append(f"task[{index}]: {message}")


def _validate_task(task: Any, index: int, errors: list[str]) -> None:
    if not isinstance(task, dict):
        _error(errors, index, "task must be a JSON object")
        return

    top_keys = set(task.keys())
    if top_keys != HIDDEN_POOL_KEYS:
        _error(
            errors,
            index,
            f"top-level keys invalid; missing={sorted(HIDDEN_POOL_KEYS - top_keys)} extra={sorted(top_keys - HIDDEN_POOL_KEYS)}",
        )

    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        _error(errors, index, "task_id must be a non-empty string")

    source = task.get("source")
    if not isinstance(source, str) or not source.strip():
        _error(errors, index, "source must be a non-empty string")

    split = task.get("split")
    if split not in {"dev", "hidden"}:
        _error(errors, index, "split must be 'dev' or 'hidden'")

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
    """Infer the task category from ``task_id``."""

    task_id = str(task.get("task_id") or "")
    match = _CATEGORY_RE.search(task_id)
    if match:
        return match.group(1)
    return "unknown"


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


def validate_pool(hidden_path: Path, train_path: Path) -> int:
    tasks = _load_tasks(hidden_path)
    train_tasks = _load_tasks(train_path)

    errors: list[str] = []

    for index, task in enumerate(tasks):
        _validate_task(task, index, errors)

    # 1000 task count and split ordering/counts
    total = len(tasks)
    if total != EXPECTED_TOTAL:
        errors.append(f"expected {EXPECTED_TOTAL} tasks, found {total}")

    dev_count = sum(1 for task in tasks if isinstance(task, dict) and task.get("split") == "dev")
    hidden_count = sum(1 for task in tasks if isinstance(task, dict) and task.get("split") == "hidden")
    if dev_count != EXPECTED_DEV:
        errors.append(f"expected {EXPECTED_DEV} dev tasks, found {dev_count}")
    if hidden_count != EXPECTED_HIDDEN:
        errors.append(f"expected {EXPECTED_HIDDEN} hidden tasks, found {hidden_count}")

    ordered_splits = [task.get("split") for task in tasks if isinstance(task, dict)]
    if ordered_splits[:EXPECTED_DEV] != ["dev"] * EXPECTED_DEV:
        errors.append("the first 200 tasks are not all marked as dev")
    if ordered_splits[EXPECTED_DEV:] != ["hidden"] * EXPECTED_HIDDEN:
        errors.append("the last 800 tasks are not all marked as hidden")

    # Uniqueness inside the hidden/dev pool
    task_ids = [str(task.get("task_id") or "") for task in tasks if isinstance(task, dict)]
    duplicate_ids = [task_id for task_id, count in Counter(task_ids).items() if count > 1]
    if duplicate_ids:
        errors.append(f"duplicate task_id values inside hidden/dev pool: {duplicate_ids[:20]}")

    instructions = [str(task.get("instruction") or "") for task in tasks if isinstance(task, dict)]
    duplicate_instructions = [instr for instr, count in Counter(instructions).items() if count > 1]
    if duplicate_instructions:
        errors.append(f"duplicate instruction values inside hidden/dev pool: {duplicate_instructions[:20]}")

    # Disjointness with the training pool
    train_ids = {str(task.get("task_id") or "") for task in train_tasks if isinstance(task, dict)}
    train_instructions = {str(task.get("instruction") or "") for task in train_tasks if isinstance(task, dict)}
    train_prefixes = {
        str(task.get("task_id") or "").split("_", 1)[0]
        for task in train_tasks
        if isinstance(task, dict) and str(task.get("task_id") or "").strip()
    }

    new_id_set = set(task_ids)
    id_overlap = sorted(new_id_set & train_ids)
    if id_overlap:
        errors.append(f"task_id overlap with training pool: {id_overlap[:20]}")

    instruction_overlap = sorted(set(instructions) & train_instructions)
    if instruction_overlap:
        errors.append(f"instruction overlap with training pool: {instruction_overlap[:20]}")

    new_prefixes = {
        str(task.get("task_id") or "").split("_", 1)[0]
        for task in tasks
        if isinstance(task, dict) and str(task.get("task_id") or "").strip()
    }
    prefix_overlap = sorted(new_prefixes & train_prefixes)
    if prefix_overlap:
        errors.append(f"task_id prefix overlap with training pool: {prefix_overlap}")

    if errors:
        print(f"Hidden/dev pool validation FAILED with {len(errors)} error(s):")
        for error in errors[:100]:
            print(f"  - {error}")
        if len(errors) > 100:
            print(f"  ... and {len(errors) - 100} more")
        return 1

    source_counts = Counter(str(task["source"]) for task in tasks)
    category_counts = Counter(_infer_category(task) for task in tasks)
    split_counts = Counter(str(task["split"]) for task in tasks)

    print(f"Hidden/dev pool validation passed: {total} tasks\n")
    _print_distribution("split distribution:", split_counts, total)
    print()
    _print_distribution("source distribution:", source_counts, total)
    print()
    _print_distribution("category distribution:", category_counts, total)
    print()
    print("disjoint checks:")
    print(f"  task_id overlap: 0")
    print(f"  instruction overlap: 0")
    print(f"  task_id prefix overlap: 0")
    print(f"  train tasks: {len(train_tasks)}")

    # coverage summary: required scenarios are present in the generated pool
    present = {category for category in TASK_CATEGORIES if category_counts.get(category, 0) > 0}
    print()
    print("required scenario coverage:")
    for category in TASK_CATEGORIES:
        actual = category_counts.get(category, 0)
        print(f"  {category}: {actual}")
    missing_required = [category for category in TASK_CATEGORIES if category_counts.get(category, 0) == 0]
    if missing_required:
        print(f"WARNING: missing required categories: {missing_required}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hidden-pool", type=Path, default=None, help="path to hidden_dev_pool.json")
    parser.add_argument("--train-pool", type=Path, default=None, help="path to task_pool.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hidden_path = args.hidden_pool or default_hidden_path()
    train_path = args.train_pool or default_train_path()
    if not hidden_path.exists():
        print(f"hidden/dev pool not found: {hidden_path}")
        return 2
    if not train_path.exists():
        print(f"training pool not found: {train_path}")
        return 2
    return validate_pool(hidden_path, train_path)


if __name__ == "__main__":
    raise SystemExit(main())
