"""Run LoCoMo through the real Klara harness and model-selected memory tool."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

from klara.app.harness import KlaraHarness, KlaraHarnessConfig
from klara.app.user_context import UserContext
from klara.context.policy import ContextPolicy
from klara.core.events import KlaraEvent
from klara.core.messages import ModelCallError
from klara.core.policies import LoopPolicy, StopReason
from klara.eval.public_memory import (
    LOCOMO_COMMIT,
    LOCOMO_DATA_SHA256,
    LOCOMO_LICENSE,
    LocomoQuestion,
    load_locomo,
    select_locomo_questions,
)
from klara.eval.public_memory_live import (
    MODEL,
    _build_corpora,
    _file_sha256,
    _mean,
    _percentile,
    _safe_relative_path,
    _stable_hash,
    locomo_exact_match,
    locomo_official_f1,
)
from klara.infra.config.loader import load_models_config
from klara.infra.config.runtime import CapabilityProfile
from klara.infra.llm.openai_compatible import (
    OpenAICompatibleLlmClient,
    OpenAICompatibleSettings,
)
from klara.memory import SentenceTransformerEmbeddingProvider
from klara.tools.registry import ToolRegistry


SCHEMA_VERSION = "klara.locomo-memory-agent.v2"
BENCHMARK_INSTRUCTION = (
    "This question concerns the user's durable conversation history. Use the "
    "memory_search tool before answering. Put the complete question in query so "
    "names, events, negations, and time cues are preserved; request exactly 20 "
    "results, and use hybrid mode. "
    "Keep event dates in the query; do not use at_time, which is only for a "
    "historical snapshot of what memory knew at an exact ISO timestamp. "
    "Then answer only from the returned memories. Return only the concise answer, "
    "without explanation. If no returned memory contains the answer, return exactly: "
    "No information available."
)


class RuntimeTraceCapture:
    """Capture only the loop's public event projection for benchmark metrics."""

    def __init__(self) -> None:
        self.events: list[KlaraEvent] = []

    def on_event(self, event: KlaraEvent) -> None:
        self.events.append(event)


def evaluate_locomo_memory_agent(
    root: Path,
    *,
    dataset_path: Path,
    checkpoint_path: Path,
    storage_root: Path,
    baseline_report_path: Path,
    per_conversation: int = 10,
    selection_offset: int = 0,
    top_k: int = 20,
    max_workers: int = 8,
    max_output_tokens: int = 1400,
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> dict[str, Any]:
    """Evaluate model-selected retrieval through KlaraHarness and KlaraLoop."""

    if _file_sha256(dataset_path) != LOCOMO_DATA_SHA256:
        raise ValueError("locomo_dataset_hash_mismatch")
    if top_k != 20:
        raise ValueError("memory_agent_frozen_top_k_must_be_20")
    turns, all_questions, dataset_stats = load_locomo(dataset_path)
    questions = select_locomo_questions(
        all_questions,
        per_conversation=per_conversation,
        selection_offset=selection_offset,
    )
    selected_hash = _stable_hash([question.case_id for question in questions])
    baseline = json.loads(baseline_report_path.read_text(encoding="utf-8"))
    baseline_hybrid = baseline["systems"]["hybrid"]
    config = {
        "schema_version": SCHEMA_VERSION,
        "dataset_sha256": LOCOMO_DATA_SHA256,
        "selected_case_ids_sha256": selected_hash,
        "selection_offset": selection_offset,
        "model": MODEL,
        "instruction_sha256": hashlib.sha256(
            BENCHMARK_INSTRUCTION.encode("utf-8")
        ).hexdigest(),
        "top_k": top_k,
        "max_output_tokens": max_output_tokens,
        "temperature": 0.0,
        "runtime": "KlaraHarness/KlaraLoop",
        "visible_tools": ["memory_search"],
        "maximum_turns": 3,
        "maximum_tool_calls": 1,
        "embedding_provider": "sentence-transformers",
        "embedding_model": embedding_model,
        "learned_embedding_cache": "shared_per_benchmark_process",
        "dense_sparse_fusion": "reciprocal-rank-fusion-k60-v1",
        "diagnostics": "final-block-reasons-and-wrapped-tool-json-v1",
    }
    config_hash = _stable_hash(config)
    completed = _load_checkpoint(checkpoint_path, config_hash=config_hash)
    storage_root.mkdir(parents=True, exist_ok=True)
    memory_path = storage_root / "locomo-agent-scoped-v1.sqlite3"
    _seed_memory_store(root, memory_path=memory_path, turns=turns)
    pending = [
        question for question in questions if question.case_id not in completed
    ]
    client = _live_client(root, max_output_tokens=max_output_tokens)
    embedding_provider = SentenceTransformerEmbeddingProvider(
        model_id=embedding_model
    )
    started = perf_counter()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _answer_case,
                root=root,
                client=client,
                question=question,
                memory_path=memory_path,
                permission_path=storage_root
                / "permissions"
                / f"{question.case_id}.sqlite3",
                top_k=top_k,
                config_hash=config_hash,
                embedding_provider=embedding_provider,
            ): question.case_id
            for question in pending
        }
        for future in as_completed(futures):
            row = future.result()
            completed[row["case_id"]] = row
            with checkpoint_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                )
                handle.write("\n")
    rows = [completed[q.case_id] for q in questions if q.case_id in completed]
    aggregate = _aggregate(rows)
    strange_p0 = sum(bool(row["strange_response_p0"]) for row in rows)
    minimum_f1 = float(baseline_hybrid["official_f1"]) - 0.03
    checks = {
        "official_dataset_hash": True,
        "balanced_ten_by_ten_subset": len(questions) == 10 * per_conversation,
        "all_cases_execute_through_klara_harness": all(
            row["runtime"] == "KlaraHarness/KlaraLoop" for row in rows
        ),
        "all_cases_completed": len(rows) == len(questions),
        "all_final_case_results_successful": all(
            row["error"] is None and row["stop_reason"] == StopReason.FINAL.value
            for row in rows
        ),
        "memory_search_call_rate_at_least_0_98": (
            aggregate["memory_search_call_rate"] >= 0.98
        ),
        "valid_memory_search_arguments_at_least_0_99": (
            aggregate["valid_memory_search_arguments_rate"] >= 0.99
        ),
        "agent_f1_not_below_direct_hybrid_by_more_than_0_03": (
            aggregate["official_f1"] >= minimum_f1
        ),
        "agent_evidence_recall_at_20_at_least_0_70": (
            aggregate["evidence_recall_at_k"] >= 0.70
        ),
        "zero_strange_response_p0": strange_p0 == 0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": "memory-architecture-benchmarks",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "benchmark": "LoCoMo",
        "task": "real_agent_model_selected_memory_retrieval_and_qa",
        "source": {
            "repository": "https://github.com/snap-research/locomo",
            "commit": LOCOMO_COMMIT,
            "dataset_sha256": LOCOMO_DATA_SHA256,
            "license": LOCOMO_LICENSE,
        },
        "selection": {
            "per_conversation": per_conversation,
            "selection_offset": selection_offset,
            "selected_questions": len(questions),
            "selected_case_ids_sha256": selected_hash,
        },
        "controls": config,
        "config_sha256": config_hash,
        "dataset": dataset_stats,
        "baseline": {
            "artifact": _safe_relative_path(baseline_report_path, root),
            "schema_version": baseline.get("schema_version"),
            "direct_hybrid_official_f1": baseline_hybrid["official_f1"],
            "direct_hybrid_exact_match": baseline_hybrid["exact_match"],
            "direct_hybrid_evidence_recall_at_20": baseline_hybrid[
                "evidence_recall_at_k"
            ],
            "interpretation": (
                "retrieval-plus-direct-answer baseline; it does not execute KlaraLoop"
            ),
        },
        "agent": aggregate,
        "comparison": {
            "agent_f1_delta_vs_direct_hybrid": round(
                aggregate["official_f1"] - baseline_hybrid["official_f1"], 6
            ),
            "agent_exact_match_delta_vs_direct_hybrid": round(
                aggregate["exact_match"] - baseline_hybrid["exact_match"], 6
            ),
            "agent_evidence_recall_delta_vs_direct_hybrid": round(
                aggregate["evidence_recall_at_k"]
                - baseline_hybrid["evidence_recall_at_k"],
                6,
            ),
        },
        "rows": [_public_row(row) for row in rows],
        "checkpoint": {
            "path": _safe_relative_path(checkpoint_path, root),
            "contains_public_dataset_text": True,
            "tracked_in_git": False,
            "sha256": _file_sha256(checkpoint_path),
        },
        "report_generation_duration_ms": int((perf_counter() - started) * 1000),
        "checks": checks,
        "passed": all(checks.values()),
        "limitations": [
            "The deterministic LoCoMo token F1 remains the primary score; no same-model self-judge replaces it.",
            "The benchmark instruction identifies the request as durable-history QA, but DeepSeek still chooses and parameterizes memory_search through the production loop.",
            "LoCoMo turns are seeded as explicit episodic records so this stage isolates runtime tool choice and retrieval; automatic memory formation is evaluated separately.",
            "The committed report removes public question, answer, memory, and prediction text; raw rows stay in the ignored checkpoint.",
            "No local GPU execution or model training occurs in this evaluation.",
        ],
    }


def _seed_memory_store(root: Path, *, memory_path: Path, turns: list[Any]) -> None:
    """Seed exact LoCoMo turn IDs once without changing the retrieval corpus."""

    del root
    corpora = _build_corpora(turns)
    seed = KlaraHarness(
        llm=_NeverCalledLlm(),
        registry=ToolRegistry([]),
        config=KlaraHarnessConfig(
            capability_profile=CapabilityProfile(
                id="locomo-seed",
                visible_tools=("memory_search",),
                hooks=(),
                trace_sink="none",
            ),
            memory_path=memory_path,
            permission_path=memory_path.with_name("seed-permissions.sqlite3"),
        ),
    )
    expected = sum(len(records) for records in corpora.values())
    for conversation_index, records in corpora.items():
        scope = replace(
            seed.memory_scope,
            tenant_id="locomo-public",
            user_id=f"conversation-{conversation_index}",
            session_id=None,
        )
        for record in records:
            seed.memory_repository.save_record(
                replace(
                    record,
                    memory_id=_scoped_evidence_id(
                        conversation_index, record.memory_id
                    ),
                    scope=scope,
                    metadata={
                        **record.metadata,
                        "locomo_dia_id": record.memory_id,
                    },
                )
            )
    actual = sum(
        len(
            seed.memory_service.list_records(
                scope=replace(
                    seed.memory_scope,
                    tenant_id="locomo-public",
                    user_id=f"conversation-{conversation_index}",
                    session_id=None,
                )
            )
        )
        for conversation_index in corpora
    )
    if actual != expected:
        raise ValueError(
            f"locomo_agent_memory_store_seed_mismatch:{actual}:{expected}"
        )


class _NeverCalledLlm:
    def complete(self, **_: Any) -> Any:  # pragma: no cover - seed-only sentinel
        raise AssertionError("seed harness must not call a model")


def _answer_case(
    *,
    root: Path,
    client: OpenAICompatibleLlmClient,
    question: LocomoQuestion,
    memory_path: Path,
    permission_path: Path,
    top_k: int,
    config_hash: str,
    embedding_provider: SentenceTransformerEmbeddingProvider,
) -> dict[str, Any]:
    trace = RuntimeTraceCapture()
    profile = CapabilityProfile(
        id="locomo-memory-agent",
        required_model_capabilities=("tools",),
        visible_tools=("memory_search",),
        hooks=(),
        trace_sink="none",
    )
    harness = KlaraHarness(
        llm=client,
        registry=ToolRegistry([]),
        config=KlaraHarnessConfig(
            model=MODEL,
            thinking_enabled=False,
            capability_profile=profile,
            loop_policy=LoopPolicy(max_turns=3, max_tool_calls=1),
            context_policy=ContextPolicy(
                max_input_tokens=16_000,
                reserved_system_tokens=2_500,
                reserved_output_tokens=1_500,
                recent_messages=6,
                minimum_recent_messages=4,
                summary_max_chars=2_400,
                tool_result_max_chars=20_000,
                chars_per_token=4,
            ),
            user_context=UserContext(
                user_id=f"conversation-{question.conversation_index}",
                display_name="LoCoMo benchmark owner",
                locale="en-US",
                timezone="UTC",
                storage_key=f"locomo-{question.conversation_index}",
                tenant_id="locomo-public",
            ),
            workspace_root=root,
            memory_path=memory_path,
            permission_path=permission_path,
            session_id=f"locomo-{question.case_id}",
            memory_embedding_provider=embedding_provider,
        ),
        models=load_models_config(root / "config"),
        hooks=(trace,),
    )
    started = perf_counter()
    prediction = ""
    error: dict[str, Any] | None = None
    result = None
    try:
        result = harness.run(
            f"{BENCHMARK_INSTRUCTION}\n\nQuestion: {question.question}",
            run_id=f"memory-agent-{question.case_id}",
        )
        prediction = result.final_answer.strip()
    except ModelCallError as exc:
        error = {"type": type(exc).__name__, "code": exc.code}
    except Exception as exc:  # pragma: no cover - defensive live boundary
        error = {"type": type(exc).__name__, "code": None}
    calls = _memory_search_calls(result.messages if result else ())
    returned = _returned_memory_ids(result.messages if result else ())
    expected = {
        _scoped_evidence_id(question.conversation_index, evidence_id)
        for evidence_id in question.evidence_ids
    }
    found = expected.intersection(returned)
    metrics = _run_metrics(trace.events)
    valid_calls = sum(_valid_memory_search_arguments(call, top_k=top_k) for call in calls)
    strange = _strange_response_reason(prediction) if error is None else None
    final_block_reasons = [
        str(event.payload.get("reason", ""))
        for event in trace.events
        if event.type == "final_answer.blocked"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "config_hash": config_hash,
        "runtime": "KlaraHarness/KlaraLoop",
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
        "memory_search_calls": calls,
        "memory_search_call_count": len(calls),
        "valid_memory_search_call_count": valid_calls,
        "interaction_turns": sum(message.role == "assistant" for message in (result.messages if result else ())),
        "stop_reason": result.stop_reason.value if result else None,
        "prompt_tokens": metrics["prompt_tokens"],
        "completion_tokens": metrics["completion_tokens"],
        "total_tokens": metrics["total_tokens"],
        "latency_ms": int((perf_counter() - started) * 1000),
        "strange_response_p0": strange,
        "final_block_reasons": final_block_reasons,
        "error": error,
    }


def _memory_search_calls(messages: Any) -> list[dict[str, Any]]:
    return [
        dict(call.arguments)
        for message in messages
        if message.role == "assistant"
        for call in message.tool_calls
        if call.name == "memory_search"
    ]


def _returned_memory_ids(messages: Any) -> list[str]:
    returned: list[str] = []
    for message in messages:
        if message.role != "tool" or message.name != "memory_search":
            continue
        payload = _json_object_from_tool_message(message.content)
        if payload is None:
            continue
        for item in payload.get("results", []):
            if isinstance(item, dict) and isinstance(item.get("memory_id"), str):
                returned.append(item["memory_id"])
    return returned


def _json_object_from_tool_message(content: str) -> dict[str, Any] | None:
    """Decode JSON whether the model boundary wrapped untrusted tool output."""

    stripped = content.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start < 0:
            return None
        try:
            value, _ = json.JSONDecoder().raw_decode(stripped[start:])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _valid_memory_search_arguments(arguments: dict[str, Any], *, top_k: int) -> bool:
    query = arguments.get("query")
    limit = arguments.get("limit", 8)
    mode = arguments.get("mode", "hybrid")
    return (
        isinstance(query, str)
        and bool(query.strip())
        and isinstance(limit, int)
        and not isinstance(limit, bool)
        and limit == top_k
        and mode == "hybrid"
        and "at_time" not in arguments
    )


def _scoped_evidence_id(conversation_index: int, evidence_id: str) -> str:
    """Disambiguate LoCoMo dialogue IDs that repeat in different conversations."""

    return f"locomo-{conversation_index:02d}:{evidence_id}"


def _run_metrics(events: list[KlaraEvent]) -> dict[str, int]:
    for event in reversed(events):
        if event.type != "run.completed":
            continue
        metrics = event.payload.get("metrics", {})
        if isinstance(metrics, dict):
            return {
                "prompt_tokens": int(metrics.get("prompt_tokens", 0)),
                "completion_tokens": int(metrics.get("completion_tokens", 0)),
                "total_tokens": int(metrics.get("total_tokens", 0)),
            }
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _strange_response_reason(prediction: str) -> str | None:
    compact = prediction.strip()
    if not compact:
        return "empty_answer"
    lowered = compact.casefold()
    if "<|dsml|" in lowered or "tool_calls" in lowered:
        return "internal_tool_protocol_leak"
    if len(compact) > 2_000:
        return "answer_exceeds_2000_chars"
    return None


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [int(row["latency_ms"]) for row in rows]
    prompt_tokens = sum(int(row["prompt_tokens"]) for row in rows)
    completion_tokens = sum(int(row["completion_tokens"]) for row in rows)
    categories: dict[str, list[dict[str, Any]]] = {}
    failure_codes: Counter[str] = Counter()
    for row in rows:
        categories.setdefault(str(row["category"]), []).append(row)
        if row["error"]:
            failure_codes[str(row["error"].get("code") or row["error"]["type"])] += 1
    total_calls = sum(int(row["memory_search_call_count"]) for row in rows)
    valid_calls = sum(int(row["valid_memory_search_call_count"]) for row in rows)
    return {
        "cases": len(rows),
        "completed": sum(row["error"] is None for row in rows),
        "official_f1": _mean(row["official_f1"] for row in rows),
        "exact_match": _mean(float(row["exact_match"]) for row in rows),
        "evidence_recall_at_k": _mean(row["evidence_recall_at_k"] for row in rows),
        "category_f1": {
            category: _mean(row["official_f1"] for row in values)
            for category, values in sorted(categories.items())
        },
        "memory_search_call_rate": _mean(
            float(row["memory_search_call_count"] > 0) for row in rows
        ),
        "exactly_one_memory_search_call_rate": _mean(
            float(row["memory_search_call_count"] == 1) for row in rows
        ),
        "valid_memory_search_arguments_rate": valid_calls / total_calls if total_calls else 0.0,
        "average_interaction_turns": _mean(row["interaction_turns"] for row in rows),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "average_total_tokens": (prompt_tokens + completion_tokens) / len(rows) if rows else 0.0,
        "p50_latency_ms": median(latencies) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "estimated_cost_usd": round(
            (prompt_tokens * 0.14 + completion_tokens * 0.28) / 1_000_000, 8
        ),
        "strange_response_p0": sum(bool(row["strange_response_p0"]) for row in rows),
        "failure_codes": dict(failure_codes),
    }


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "category": row["category"],
        "official_f1": row["official_f1"],
        "exact_match": row["exact_match"],
        "evidence_recall_at_k": row["evidence_recall_at_k"],
        "memory_search_call_count": row["memory_search_call_count"],
        "valid_memory_search_call_count": row["valid_memory_search_call_count"],
        "interaction_turns": row["interaction_turns"],
        "stop_reason": row["stop_reason"],
        "answer_sha256": row["answer_sha256"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "latency_ms": row["latency_ms"],
        "strange_response_p0": row["strange_response_p0"],
        "error": row["error"],
    }


def _load_checkpoint(path: Path, *, config_hash: str) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("config_hash") == config_hash and row.get("error") is None:
            rows[str(row["case_id"])] = row
    return rows


def _live_client(root: Path, *, max_output_tokens: int) -> OpenAICompatibleLlmClient:
    models = load_models_config(root / "config")
    return OpenAICompatibleLlmClient(
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


def render_markdown(
    report: dict[str, Any],
    *,
    language: str = "zh",
    output_stem: str = "memory-architecture-agent-live",
) -> str:
    zh = language == "zh"
    title = "# Memory Agent 架构实测" if zh else "# Memory Agent Architecture Evaluation"
    agent = report["agent"]
    baseline = report["baseline"]
    lines = [
        title,
        "",
        (
            f"语言：中文 | [English](./{output_stem}.en.md)"
            if zh
            else f"Language: [Chinese](./{output_stem}.md) | English"
        ),
        "",
        ("## 结论" if zh else "## Result"),
        "",
        ("通过" if report["passed"] else "未通过") if zh else ("PASS" if report["passed"] else "FAIL"),
        "",
        ("## 冻结成绩" if zh else "## Frozen score"),
        "",
        "| System | F1 | EM | Recall@20 | Tool call rate |",
        "|---|---:|---:|---:|---:|",
        f"| Direct hybrid baseline | {baseline['direct_hybrid_official_f1']:.6f} | {baseline['direct_hybrid_exact_match']:.6f} | {baseline['direct_hybrid_evidence_recall_at_20']:.6f} | N/A |",
        f"| KlaraLoop memory agent | {agent['official_f1']:.6f} | {agent['exact_match']:.6f} | {agent['evidence_recall_at_k']:.6f} | {agent['memory_search_call_rate']:.6f} |",
        "",
        ("## 运行指标" if zh else "## Runtime metrics"),
        "",
        f"- Cases: {agent['completed']}/{agent['cases']}",
        f"- Valid tool arguments: {agent['valid_memory_search_arguments_rate']:.6f}",
        f"- Average turns: {agent['average_interaction_turns']:.3f}",
        f"- P50/P95 latency: {agent['p50_latency_ms']:.0f}/{agent['p95_latency_ms']:.0f} ms",
        f"- Estimated DeepSeek cost: ${agent['estimated_cost_usd']:.6f}",
        "",
        ("## 门槛" if zh else "## Gates"),
        "",
    ]
    lines.extend(f"- {'PASS' if value else 'FAIL'} — `{name}`" for name, value in report["checks"].items())
    lines.extend(["", ("## 限制" if zh else "## Limitations"), ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument(
        "--baseline-report",
        type=Path,
        default=Path("docs/reports/product/agent-product-memory-locomo-same-model.json"),
    )
    parser.add_argument("--per-conversation", type=int, default=10)
    parser.add_argument("--selection-offset", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--max-output-tokens", type=int, default=1400)
    parser.add_argument(
        "--embedding-model",
        default="sentence-transformers/all-MiniLM-L6-v2",
    )
    parser.add_argument("--output-stem", default="memory-architecture-agent-live")
    args = parser.parse_args()
    root = args.root.resolve()
    baseline = args.baseline_report
    if not baseline.is_absolute():
        baseline = root / baseline
    report = evaluate_locomo_memory_agent(
        root,
        dataset_path=args.dataset.resolve(),
        checkpoint_path=args.checkpoint.resolve(),
        storage_root=args.storage_root.resolve(),
        baseline_report_path=baseline.resolve(),
        per_conversation=args.per_conversation,
        selection_offset=args.selection_offset,
        top_k=args.top_k,
        max_workers=args.max_workers,
        max_output_tokens=args.max_output_tokens,
        embedding_model=args.embedding_model,
    )
    output = root / "docs" / "reports" / "product"
    output.mkdir(parents=True, exist_ok=True)
    stem = args.output_stem
    (output / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    (output / f"{stem}.md").write_text(
        render_markdown(report, output_stem=stem), encoding="utf-8", newline="\n"
    )
    (output / f"{stem}.en.md").write_text(
        render_markdown(report, language="en", output_stem=stem),
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"passed": report["passed"], "agent": report["agent"]}))


if __name__ == "__main__":
    main()
