"""Offline rescore of stored eval reports with strict + type-normalized metrics.

Keeps the original strict contract untouched and adds a deterministic,
type-normalized rescore so that argument types/values are compared semantically
instead of byte-for-byte. An optional LLM-as-judge column can be enabled later.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO / "src") not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_REPO / "src"))

from klara.eval.three_way_eval import (  # noqa: E402
    EvalBenchmark,
    ExpectedToolCall,
    _answer_matches,
    _expected_matches_observed,
    _normalize_answer,
    _ratio,
    tool_call_accuracy,
)


# ---------------------------------------------------------------------------
# Deterministic normalized matching
# ---------------------------------------------------------------------------

_ALIASES = {
    "websearch": "web_search",
    "web_fetch": "web_fetch",
    "fetchweb": "web_fetch",
    "currenttime": "current_time",
    "getcurrenttime": "current_time",
    "memorysearch": "memory_search",
    "searchmemory": "memory_search",
    "skillslist": "skills_list",
    "listskills": "skills_list",
    "skillview": "skill_view",
    "viewskill": "skill_view",
}


def normalize_tool_name(name: str) -> str:
    text = str(name).casefold().strip()
    text = re.sub(r"[\s\-_.]+", "_", text)
    text = text.strip("_")
    if text in _ALIASES:
        return _ALIASES[text]
    return text


def _norm_value(value: Any) -> Any:
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int) and not isinstance(value, bool):
        return ("num", float(value))
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ("num", repr(value))
        return ("num", value)
    if isinstance(value, str):
        text = value.casefold().strip()
        text = "".join(text.split())
        return ("str", text.replace("“", '"').replace("”", '"'))
    if isinstance(value, (list, tuple)):
        return ("list", tuple(_norm_value(item) for item in value))
    if isinstance(value, dict):
        return (
            "dict",
            tuple(
                sorted(
                    (normalize_tool_name(k), _norm_value(v))
                    for k, v in value.items()
                )
            ),
        )
    if value is None:
        return ("none", None)
    return ("str", str(value))


def _norm_args_match(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    if not isinstance(expected, dict) or not isinstance(observed, dict):
        return expected == observed
    for key, want in expected.items():
        if key not in observed:
            return False
        if _norm_value(want) != _norm_value(observed[key]):
            return False
    return True


def _normalized_tool_call_accuracy(
    task_expected: tuple[ExpectedToolCall, ...],
    observed: tuple[dict[str, Any], ...],
    *,
    ordered: bool = False,
) -> float:
    if not task_expected and not observed:
        return 1.0
    if not task_expected or not observed:
        return 0.0
    remaining = list(observed)
    matched = 0
    cursor = 0
    for want in task_expected:
        for index, cand in enumerate(remaining):
            if normalize_tool_name(want.name) != normalize_tool_name(cand["name"]):
                continue
            if not _norm_args_match(want.arguments, cand.get("arguments", {})):
                continue
            if ordered and index < cursor:
                continue
            matched += 1
            remaining.pop(index)
            cursor = index
            break
    return _ratio(matched, max(len(task_expected), len(observed)))


def _number_set(text: str) -> set[float]:
    return {float(item) for item in re.findall(r"-?\d+(?:\.\d+)?", text)}


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _answer_match_normalized(expected: tuple[str, ...], final_answer: str) -> bool:
    # Strict substring match first (identical to the frozen contract).
    if not expected:
        return bool(final_answer)
    norm_final = _normalize_answer(final_answer)
    for item in expected:
        if item and _normalize_answer(item) in norm_final:
            return True
    # Relaxed token/number coverage for cases where the model paraphrases or
    # adds units/whitespace that strict substring matching rejects.
    if not norm_final:
        return False
    for item in expected:
        if not item:
            continue
        want_norm = _normalize_answer(item)
        want_tokens = _token_set(want_norm)
        have_tokens = _token_set(norm_final)
        want_nums = _number_set(want_norm)
        have_nums = _number_set(norm_final)
        if want_nums - have_nums:
            continue
        if want_tokens - have_tokens:
            continue
        return True
    return False


def rescore_one(
    task: dict[str, Any],
    gold: Any,
    *,
    ordered: bool = False,
) -> dict[str, Any]:
    observed = tuple(
        {
            "name": call.get("name", ""),
            "arguments": call.get("arguments", {}),
        }
        for call in task.get("observed_tool_calls", [])
    )
    expected = tuple(gold.expected_tool_calls) if gold else ()
    expected_answers = tuple(gold.acceptable_answers) + (
        (gold.reference_answer,) if getattr(gold, "reference_answer", None) else ()
    )

    strict_acc = tool_call_accuracy(
        gold or _empty_task(),  # type: ignore[arg-type]
        tuple(
            __import__("klara.core.tools", fromlist=["ToolCall"]).ToolCall(
                id=str(call.get("id", "")), name=call.get("name", ""), arguments=call.get("arguments", {})
            )
            for call in task.get("observed_tool_calls", [])
        ),
        ordered=ordered,
    ) if gold else 1.0

    norm_acc = _normalized_tool_call_accuracy(expected, observed, ordered=ordered)
    final_answer = str(task.get("final_answer", ""))
    strict_answer = _answer_matches(gold, final_answer) if gold else bool(final_answer)
    norm_answer = _answer_match_normalized(expected_answers, final_answer)

    error = task.get("error")
    has_error = bool(error)
    success_strict = bool(strict_answer and not has_error)
    success_norm = bool(norm_answer and not has_error)
    if gold and not expected_answers:
        success_strict = bool(not has_error and strict_acc >= 1.0)
        success_norm = bool(not has_error and norm_acc >= 1.0)

    return {
        "tool_call_accuracy_strict": strict_acc,
        "tool_call_accuracy_normalized": norm_acc,
        "answer_match_strict": strict_answer,
        "answer_match_normalized": norm_answer,
        "success_strict": success_strict,
        "success_normalized": success_norm,
    }


def _empty_task():
    from klara.eval.three_way_eval import EvalTask
    return EvalTask(id="", user_turn="")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True, action="append")
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--output", default="results/rescore_summary.json")
    ap.add_argument("--ordered", action="store_true")
    args = ap.parse_args()

    benchmark, _ = load_bundle(args.fixture)
    gold_by_id = {task.id: task for task in benchmark.tasks}

    summary = []
    for result_path in args.result:
        raw = json.loads(Path(result_path).read_text(encoding="utf-8-sig"))
        rows = []
        for task in raw.get("tasks", []):
            gold = gold_by_id.get(task.get("task_id"))
            rescored = rescore_one(task, gold, ordered=args.ordered)
            rows.append({**task, "rescored": rescored})
        totals = _aggregate(rows)
        summary.append(
            {
                "result": str(result_path),
                "model": raw.get("model"),
                "benchmark": raw.get("benchmark"),
                "original": raw.get("metrics"),
                "rescored": totals,
            }
        )
        out_path = Path(str(result_path)).with_suffix(".rescored.json")
        out_path.write_text(
            json.dumps(
                {**raw, "tasks": rows, "rescored_metrics": totals},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {out_path}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _print_table(summary)
    return 0


def load_bundle(path: str):
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return EvalBenchmark.from_dict(raw), raw


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {
        "task_success_strict": _ratio(sum(r["rescored"]["success_strict"] for r in rows), n),
        "task_success_normalized": _ratio(sum(r["rescored"]["success_normalized"] for r in rows), n),
        "tool_call_accuracy_strict": _ratio(
            sum(r["rescored"]["tool_call_accuracy_strict"] for r in rows), n
        ),
        "tool_call_accuracy_normalized": _ratio(
            sum(r["rescored"]["tool_call_accuracy_normalized"] for r in rows), n
        ),
    }


def _print_table(summary: list[dict[str, Any]]) -> None:
    print("\nmodel\t\t\torig_task_succ\tstrict_task_succ\tnorm_task_succ\tstrict_tool_acc\tnorm_tool_acc")
    for item in summary:
        orig = item["original"] or {}
        res = item["rescored"]
        print(
            f"{str(item['model'])[:20]:20}\t"
            f"{float(orig.get('task_success', 0)):.3f}\t\t"
            f"{res['task_success_strict']:.3f}\t\t"
            f"{res['task_success_normalized']:.3f}\t\t"
            f"{res['tool_call_accuracy_strict']:.3f}\t\t"
            f"{res['tool_call_accuracy_normalized']:.3f}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
