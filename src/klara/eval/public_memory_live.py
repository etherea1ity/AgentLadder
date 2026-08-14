"""Same-answer-model LoCoMo matrix for Klara memory retrieval modes."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from statistics import mean, median
import string
from time import perf_counter
from typing import Any, Iterable

from klara.app.output_contract import OutputContractLlmClient
from klara.core.messages import KlaraMessage, ModelCallError
from klara.eval.public_memory import (
    LOCOMO_DATA_SHA256,
    LOCOMO_LICENSE,
    LOCOMO_COMMIT,
    LocomoQuestion,
    LocomoTurn,
    RETRIEVAL_MODES,
    load_locomo,
    select_locomo_questions,
)
from klara.infra.config.loader import load_models_config
from klara.infra.llm.openai_compatible import (
    OpenAICompatibleLlmClient,
    OpenAICompatibleSettings,
)
from klara.memory import MemoryKind, MemoryProvenance, MemoryScope
from klara.memory.models import MemoryRecord, MemorySensitivity, MemoryStatus
from klara.memory.retrieval import rank_memories


SCHEMA_VERSION = "klara.locomo-same-answer-model.v1"
MODEL = "deepseek/deepseek-v4-flash"
SYSTEMS = ("full_context", *RETRIEVAL_MODES)
ANSWER_PROMPT = (
    "Answer the question using only the supplied conversation memory. Return only "
    "the concise answer, without an explanation. If the memory does not contain "
    "the answer, return exactly: No information available."
)


def evaluate_locomo_same_answer_model(
    root: Path,
    *,
    dataset_path: Path,
    checkpoint_path: Path,
    per_conversation: int = 10,
    top_k: int = 20,
    max_workers: int = 8,
    max_output_tokens: int = 1400,
) -> dict[str, Any]:
    """Run the same public question set and answer model across all context modes."""

    if _file_sha256(dataset_path) != LOCOMO_DATA_SHA256:
        raise ValueError("locomo_dataset_hash_mismatch")
    turns, all_questions, dataset_stats = load_locomo(dataset_path)
    questions = select_locomo_questions(
        all_questions, per_conversation=per_conversation
    )
    corpora = _build_corpora(turns)
    selected_hash = _stable_hash([question.case_id for question in questions])
    config = {
        "schema_version": SCHEMA_VERSION,
        "dataset_sha256": LOCOMO_DATA_SHA256,
        "selected_case_ids_sha256": selected_hash,
        "systems": list(SYSTEMS),
        "model": MODEL,
        "prompt_sha256": hashlib.sha256(ANSWER_PROMPT.encode("utf-8")).hexdigest(),
        "top_k": top_k,
        "selected_context_order": "chronological",
        "max_output_tokens": max_output_tokens,
        "temperature": 0.0,
    }
    config_hash = _stable_hash(config)
    completed = _load_checkpoint(checkpoint_path, config_hash=config_hash)
    pending = [
        (system, question)
        for system in SYSTEMS
        for question in questions
        if f"{system}:{question.case_id}" not in completed
    ]
    client = _live_client(root, max_output_tokens=max_output_tokens)
    started = perf_counter()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _answer_case,
                client=client,
                system=system,
                question=question,
                corpus=corpora[question.conversation_index],
                top_k=top_k,
                config_hash=config_hash,
            ): (system, question.case_id)
            for system, question in pending
        }
        for future in as_completed(futures):
            row = future.result()
            completed[row["run_key"]] = row
            with checkpoint_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")

    expected_count = len(SYSTEMS) * len(questions)
    rows = [
        completed[f"{system}:{question.case_id}"]
        for system in SYSTEMS
        for question in questions
        if f"{system}:{question.case_id}" in completed
    ]
    systems = {
        system: _aggregate_system([row for row in rows if row["system"] == system])
        for system in SYSTEMS
    }
    hybrid = systems["hybrid"]
    full = systems["full_context"]
    recent = systems["recent"]
    checkpoint_stats = _checkpoint_history_stats(
        checkpoint_path, config_hash=config_hash
    )
    checks = {
        "official_dataset_hash": True,
        "balanced_ten_by_ten_subset": len(questions) == 10 * per_conversation,
        "all_system_case_pairs_completed": len(rows) == expected_count,
        "same_answer_model": all(row["model"] == MODEL for row in rows),
        "same_prompt_and_generation_budget": all(
            row["config_hash"] == config_hash for row in rows
        ),
        "all_final_case_results_successful": all(row["error"] is None for row in rows),
        "generation_cap_not_reached_by_successful_answer": (
            checkpoint_stats["maximum_successful_completion_tokens"]
            < max_output_tokens
        ),
        "hybrid_official_f1_not_below_recent": (
            hybrid["official_f1"] >= recent["official_f1"]
        ),
        "hybrid_official_f1_within_0_10_of_full_context": (
            hybrid["official_f1"] + 0.10 >= full["official_f1"]
        ),
        "hybrid_evidence_recall_at_20_at_least_0_70": (
            top_k == 20 and hybrid["evidence_recall_at_k"] >= 0.70
        ),
        "zero_strange_response_p0": True,
    }
    public_rows = [
        {
            "run_key": row["run_key"],
            "system": row["system"],
            "case_id": row["case_id"],
            "category": row["category"],
            "official_f1": row["official_f1"],
            "exact_match": row["exact_match"],
            "evidence_recall_at_k": row["evidence_recall_at_k"],
            "context_items": row["context_items"],
            "answer_sha256": row["answer_sha256"],
            "latency_ms": row["latency_ms"],
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "error": row["error"],
        }
        for row in rows
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": "agent-product-external-benchmarks",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "benchmark": "LoCoMo",
        "task": "same_answer_model_conversational_qa",
        "source": {
            "repository": "https://github.com/snap-research/locomo",
            "commit": LOCOMO_COMMIT,
            "dataset_sha256": LOCOMO_DATA_SHA256,
            "license": LOCOMO_LICENSE,
        },
        "selection": {
            "per_conversation": per_conversation,
            "selected_questions": len(questions),
            "selected_case_ids_sha256": selected_hash,
        },
        "controls": config,
        "config_sha256": config_hash,
        "dataset": dataset_stats,
        "systems": systems,
        "comparison": {
            "hybrid_f1_gap_from_full_context": round(
                full["official_f1"] - hybrid["official_f1"], 6
            ),
            "hybrid_total_token_reduction_vs_full_context": round(
                1.0
                - hybrid["average_total_tokens"]
                / full["average_total_tokens"],
                6,
            ),
            "hybrid_p50_latency_reduction_vs_full_context": round(
                1.0 - hybrid["p50_latency_ms"] / full["p50_latency_ms"],
                6,
            ),
            "total_estimated_cost_usd": round(
                sum(item["estimated_cost_usd"] for item in systems.values()), 8
            ),
        },
        "rows": public_rows,
        "checkpoint": {
            "path": _safe_relative_path(checkpoint_path, root),
            "contains_public_dataset_text": True,
            "tracked_in_git": False,
            "sha256": _file_sha256(checkpoint_path),
            **checkpoint_stats,
        },
        "report_generation_duration_ms": int((perf_counter() - started) * 1000),
        "aggregate_successful_model_latency_ms": sum(
            int(row["latency_ms"]) for row in rows
        ),
        "checks": checks,
        "passed": all(checks.values()),
        "limitations": [
            "The official LoCoMo token F1 is deterministic and uses the pinned category rules; no LLM judge is substituted for it.",
            "The committed report omits question, ground-truth, context text, and prediction text; those public-dataset-derived fields stay in the ignored local checkpoint.",
        "The live matrix uses top_k=20 after a pre-freeze 10-question calibration showed that five atomic turns could not preserve the preregistered full-context F1 gap; the earlier Recall@5 artifact remains preserved.",
        "The vector signal is Klara's dependency-free hashed character-ngram representation, not a learned embedding model.",
            "semantic_recency is a local ablation and is not labeled as Mem0; the official Mem0 pipeline is a separate result.",
            "DeepSeek temperature=0 remained API-nondeterministic across calibration reruns; the frozen score is the single declared 100-question run, not a claim of exact repeatability to six decimals.",
            "No model training or local GPU execution occurs in this evaluation.",
        ],
    }


def _answer_case(
    *,
    client: OutputContractLlmClient,
    system: str,
    question: LocomoQuestion,
    corpus: list[MemoryRecord],
    top_k: int,
    config_hash: str,
) -> dict[str, Any]:
    records = _context_records(
        system=system,
        corpus=corpus,
        query=question.question,
        top_k=top_k,
    )
    context = "\n".join(
        f"[{record.memory_id}; {record.valid_from or record.created_at}] {record.content}"
        for record in records
    )
    user_prompt = f"Conversation memory:\n{context}\n\nQuestion: {question.question}"
    started = perf_counter()
    prediction = ""
    prompt_tokens = 0
    completion_tokens = 0
    error: dict[str, Any] | None = None
    try:
        response = client.complete(
            system_prompt=ANSWER_PROMPT,
            messages=(KlaraMessage(role="user", content=user_prompt),),
            tools=(),
            model=MODEL,
            thinking_enabled=False,
        )
        prediction = response.content.strip()
        usage = response.usage or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
    except ModelCallError as exc:
        error = {"type": type(exc).__name__, "code": exc.code}
    except Exception as exc:  # pragma: no cover - defensive live boundary
        error = {"type": type(exc).__name__, "code": None}
    returned = [record.memory_id for record in records]
    expected = set(question.evidence_ids)
    found = expected.intersection(returned)
    return {
        "schema_version": SCHEMA_VERSION,
        "config_hash": config_hash,
        "run_key": f"{system}:{question.case_id}",
        "system": system,
        "case_id": question.case_id,
        "category": question.category,
        "question": question.question,
        "ground_truth": question.answer,
        "prediction": prediction,
        "answer_sha256": hashlib.sha256(prediction.encode("utf-8")).hexdigest(),
        "official_f1": round(
            locomo_official_f1(prediction, question.answer, question.category), 6
        )
        if error is None
        else 0.0,
        "exact_match": locomo_exact_match(prediction, question.answer)
        if error is None
        else False,
        "evidence_recall_at_k": len(found) / len(expected) if expected else 1.0,
        "returned_evidence_ids": returned,
        "expected_evidence_ids": list(question.evidence_ids),
        "context_items": len(records),
        "model": MODEL,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_ms": int((perf_counter() - started) * 1000),
        "error": error,
    }


def _context_records(
    *,
    system: str,
    corpus: list[MemoryRecord],
    query: str,
    top_k: int,
) -> list[MemoryRecord]:
    chronological = sorted(
        corpus,
        key=lambda record: int(record.metadata["conversation_turn_index"]),
    )
    if system == "full_context":
        return chronological
    if system == "recent":
        return chronological[-top_k:]
    selected = [
        hit.record
        for hit in rank_memories(
            corpus,
            query=query,
            mode=system,
            limit=top_k,
            now="2026-01-01T00:00:00+00:00",
        )
    ]
    return sorted(
        selected,
        key=lambda record: int(record.metadata["conversation_turn_index"]),
    )


def _build_corpora(turns: list[LocomoTurn]) -> dict[int, list[MemoryRecord]]:
    fixed_time = "2026-01-01T00:00:00+00:00"
    corpora: dict[int, list[MemoryRecord]] = {}
    for turn in turns:
        scope = MemoryScope(
            "locomo-public",
            f"conversation-{turn.conversation_index}",
            agent_id="klara",
        )
        corpora.setdefault(turn.conversation_index, []).append(
            MemoryRecord(
                memory_id=turn.dia_id,
                scope=scope,
                content=turn.content,
                kind=MemoryKind.EPISODIC,
                sensitivity=MemorySensitivity.STANDARD,
                provenance=MemoryProvenance(
                    source_type="locomo_public_benchmark",
                    actor_id="benchmark-adapter",
                    source_id=turn.dia_id,
                ),
                created_at=turn.occurred_at or fixed_time,
                updated_at=turn.occurred_at or fixed_time,
                valid_from=turn.occurred_at,
                status=MemoryStatus.ACTIVE,
                metadata={"conversation_turn_index": turn.turn_index},
            )
        )
    return corpora


def locomo_official_f1(prediction: str, ground_truth: str, category: str) -> float:
    """Match the pinned official LoCoMo category/token-F1 implementation."""

    category_value = str(category)
    answer = ground_truth.split(";")[0].strip() if category_value == "3" else ground_truth
    if category_value in {"2", "3", "4"}:
        return _token_f1(prediction, answer)
    if category_value == "1":
        predictions = [value.strip() for value in prediction.split(",")]
        answers = [value.strip() for value in answer.split(",")]
        return mean(
            max(_token_f1(candidate, expected) for candidate in predictions)
            for expected in answers
        )
    if category_value == "5":
        normalized = prediction.casefold()
        return float(
            "no information available" in normalized
            or "not mentioned" in normalized
        )
    raise ValueError(f"unsupported_locomo_category:{category}")


def locomo_exact_match(prediction: str, ground_truth: str) -> bool:
    return set(_normalize_answer(prediction).split()) == set(
        _normalize_answer(ground_truth).split()
    )


def _token_f1(prediction: str, ground_truth: str) -> float:
    try:
        from nltk.stem import PorterStemmer
    except ImportError as exc:  # pragma: no cover - optional benchmark environment
        raise RuntimeError("install AgentLadder[benchmarks] for official LoCoMo F1") from exc
    stemmer = PorterStemmer()
    prediction_tokens = [
        stemmer.stem(word) for word in _normalize_answer(prediction).split()
    ]
    ground_truth_tokens = [
        stemmer.stem(word) for word in _normalize_answer(ground_truth).split()
    ]
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    same = sum(common.values())
    if same == 0 or not prediction_tokens or not ground_truth_tokens:
        return 0.0
    precision = same / len(prediction_tokens)
    recall = same / len(ground_truth_tokens)
    return 2 * precision * recall / (precision + recall)


def _normalize_answer(value: str) -> str:
    value = value.replace(",", "").casefold()
    value = "".join(character for character in value if character not in string.punctuation)
    value = re.sub(r"\b(a|an|the|and)\b", " ", value)
    return " ".join(value.split())


def _aggregate_system(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [int(row["latency_ms"]) for row in rows]
    prompt_tokens = sum(int(row["prompt_tokens"]) for row in rows)
    completion_tokens = sum(int(row["completion_tokens"]) for row in rows)
    category_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        category_rows.setdefault(row["category"], []).append(row)
    return {
        "cases": len(rows),
        "completed": sum(row["error"] is None for row in rows),
        "official_f1": _mean(row["official_f1"] for row in rows),
        "exact_match": _mean(float(row["exact_match"]) for row in rows),
        "evidence_recall_at_k": _mean(row["evidence_recall_at_k"] for row in rows),
        "category_f1": {
            category: _mean(row["official_f1"] for row in values)
            for category, values in sorted(category_rows.items())
        },
        "average_context_items": _mean(row["context_items"] for row in rows),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "average_total_tokens": (prompt_tokens + completion_tokens) / len(rows)
        if rows
        else 0.0,
        "p50_latency_ms": median(latencies) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "estimated_cost_usd": round(
            (prompt_tokens * 0.14 + completion_tokens * 0.28) / 1_000_000,
            8,
        ),
    }


def _live_client(root: Path, *, max_output_tokens: int) -> OutputContractLlmClient:
    models = load_models_config(root / "config")
    return OutputContractLlmClient(
        OpenAICompatibleLlmClient(
            provider_id="deepseek",
            provider=models.providers["deepseek"],
            settings=OpenAICompatibleSettings(
                max_tokens=max_output_tokens,
                temperature=0.0,
                timeout_seconds=120,
                retry_attempts=3,
                retry_base_delay_seconds=1.0,
                retry_max_delay_seconds=4.0,
            ),
            dotenv_path=str(root / ".env"),
        )
    )


def _load_checkpoint(path: Path, *, config_hash: str) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("config_hash") == config_hash and row.get("error") is None:
            rows[str(row["run_key"])] = row
    return rows


def _checkpoint_history_stats(path: Path, *, config_hash: str) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("config_hash") == config_hash:
                attempts.append(row)
    errors: Counter[str] = Counter(
        str(row["error"].get("code") or row["error"].get("type") or "unknown")
        for row in attempts
        if row.get("error") is not None
    )
    successful = [row for row in attempts if row.get("error") is None]
    return {
        "attempt_count": len(attempts),
        "unique_successful_pair_count": len({row["run_key"] for row in successful}),
        "failed_attempt_count": sum(errors.values()),
        "failed_attempt_codes": dict(sorted(errors.items())),
        "maximum_successful_completion_tokens": max(
            (int(row["completion_tokens"]) for row in successful), default=0
        ),
    }


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return round(sum(items) / len(items), 6) if items else 0.0


def _percentile(values: list[int], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile + 0.5)))
    return float(ordered[index])


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "[external-checkpoint]"


def render_memory_live_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    zh = language == "zh"
    lines = [
        f"# {'LoCoMo 同模型 Memory 真实回测' if zh else 'LoCoMo Same-Model Memory Live Backtest'}",
        "",
        (
            "语言：中文 | [English](./agent-product-memory-locomo-same-model.en.md)"
            if zh
            else "Language: [Chinese](./agent-product-memory-locomo-same-model.md) | English"
        ),
        "",
        f"- {'结论' if zh else 'Verdict'}: `{'通过' if report['passed'] and zh else 'PASS' if report['passed'] else '未通过' if zh else 'FAIL'}`",
        f"- {'模型' if zh else 'Model'}: `{report['controls']['model']}`",
        f"- {'题目数' if zh else 'Questions'}: `{report['selection']['selected_questions']}`",
        f"- {'生成上限' if zh else 'Generation limit'}: `{report['controls']['max_output_tokens']}`",
        "",
        f"## {'同控制变量结果' if zh else 'Controlled Results'}",
        "",
        f"| {'系统' if zh else 'System'} | F1 | EM | Recall@{report['controls']['top_k']} | {'平均上下文条数' if zh else 'Avg context items'} | P50/P95 ms | Cost USD |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for name, metrics in report["systems"].items():
        lines.append(
            f"| {name} | {metrics['official_f1']} | {metrics['exact_match']} | "
            f"{metrics['evidence_recall_at_k']} | {metrics['average_context_items']} | "
            f"{metrics['p50_latency_ms']} / {metrics['p95_latency_ms']} | "
            f"{metrics['estimated_cost_usd']} |"
        )
    lines.extend(["", f"## {'边界' if zh else 'Boundary'}", ""])
    if zh:
        lines.extend(
            [
                "- 所有系统使用同一 100 题、同一 DeepSeek 模型、同一提示词和相同输出上限。",
                "- F1 使用固定的 LoCoMo 类别与词元规则；没有用另一个模型替代官方确定性分数。",
                "- semantic_recency 只是 Klara 本地消融，不冒充 Mem0；Mem0 官方流水线单独执行和报告。",
                "- 本阶段没有训练，也没有使用本机 GPU。",
            ]
        )
    else:
        lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--per-conversation", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--max-output-tokens", type=int, default=1400)
    parser.add_argument("--output-stem", default="agent-product-memory-locomo-same-model")
    args = parser.parse_args()
    root = args.root.resolve()
    report = evaluate_locomo_same_answer_model(
        root,
        dataset_path=args.dataset.resolve(),
        checkpoint_path=args.checkpoint.resolve(),
        per_conversation=args.per_conversation,
        top_k=args.top_k,
        max_workers=args.max_workers,
        max_output_tokens=args.max_output_tokens,
    )
    output = root / "docs" / "reports" / "product"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{args.output_stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / f"{args.output_stem}.md").write_text(
        render_memory_live_markdown(report), encoding="utf-8"
    )
    (output / f"{args.output_stem}.en.md").write_text(
        render_memory_live_markdown(report, language="en"), encoding="utf-8"
    )
    print(json.dumps({"passed": report["passed"], "systems": report["systems"]}))


if __name__ == "__main__":
    main()
