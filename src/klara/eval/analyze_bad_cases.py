"""Analyze Klara dev-eval bad cases by task category and emit an augmentation plan."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def category_of(task_id: str) -> str:
    m = re.search(r"_(single_tool|multi_tool|sequential|argument_constraint|failure_retry|multi_turn|no_tool|evidence_synthesis)_", task_id)
    return m.group(1) if m else "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--task-pool", default="data/tasks/task_pool.json")
    ap.add_argument("--out", default="data/tasks/bad_case_augmentation.json")
    args = ap.parse_args()

    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    tasks = result.get("tasks", [])
    failed = [t for t in tasks if not t.get("success")]

    by_cat = Counter(category_of(t["task_id"]) for t in tasks)
    fail_cat = Counter(category_of(t["task_id"]) for t in failed)
    print("category\tfail\tok")
    for cat in sorted(by_cat):
        print(f"{cat}\t{fail_cat.get(cat,0)}\t{by_cat[cat]-fail_cat.get(cat,0)}")

    pool = json.loads(Path(args.task_pool).read_text(encoding="utf-8"))
    pool_by_cat = defaultdict(list)
    for t in pool:
        pool_by_cat[category_of(t["task_id"])].append(t)

    # Select extra tasks in failing categories, up to 200 per category.
    aug = []
    for cat in sorted(fail_cat):
        candidates = [t for t in pool_by_cat.get(cat, [])]
        # take first `need` that are not already the first 2000 used; simple deterministic slice
        need = min(fail_cat[cat], 200)
        aug.extend(candidates[:need])

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(aug, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"augmentation tasks: {len(aug)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
