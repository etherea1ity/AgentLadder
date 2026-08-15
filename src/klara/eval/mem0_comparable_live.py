"""Same-control LoCoMo evaluation for the provenance-pinned official Mem0 v3 SDK."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from statistics import mean, median
from threading import Lock
from time import perf_counter, sleep
from typing import Any, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from klara.core.messages import KlaraMessage, ModelCallError
from klara.eval.product_freeze_readiness import render_ledger, render_report
from klara.eval.public_memory import (
    LOCOMO_COMMIT,
    LOCOMO_DATA_SHA256,
    LOCOMO_LICENSE,
    LocomoQuestion,
    inspect_public_source,
    load_locomo,
    select_locomo_questions,
)
from klara.eval.public_memory_live import (
    ANSWER_PROMPT,
    MODEL,
    _live_client,
    _stable_hash,
    locomo_exact_match,
    locomo_official_f1,
)


SCHEMA_VERSION = "klara.mem0-comparable-reproduction.v2"
STAGE_ID = "mem0-comparable-reproduction"
STAGE_BRANCH = "codex/mem0-comparable-reproduction"
MEM0_BENCHMARK_COMMIT = "4b61c5d31b9c668a12b4f5e78064248a02c82d2b"
MEM0_PR_HEAD = "5e941e24c2cb260f73cc6d31113a92bb1ce62d46"
SELECTED_CASE_IDS_SHA256 = (
    "8b80b91c5730abb9343ae9095799e60d255b3572a11c62bfdc3508fb0d263e12"
)
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
HTTP_MAX_ATTEMPTS = 16
HTTP_BACKOFF_CAP_SECONDS = 4
_CHECKPOINT_LOCK = Lock()


@dataclass(frozen=True)
class OfficialIngestionTurn:
    """One turn encoded with the official memory-benchmarks LoCoMo conventions."""

    conversation_index: int
    turn_index: int
    dia_id: str
    role: str
    content: str
    occurred_at: str | None

    @property
    def ingest_key(self) -> str:
        """Return a deterministic per-turn checkpoint key."""

        return f"locomo-{self.conversation_index:02d}:{self.dia_id}"


class Mem0HttpClient:
    """Small retrying client for the local official-SDK container."""

    def __init__(self, base_url: str, *, timeout_seconds: int = 300) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, Any]:
        """Read the sanitized server provenance response."""

        return self._request("GET", "/health")

    def add(
        self,
        *,
        messages: list[dict[str, str]],
        user_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute official Mem0 v3 formation for one benchmark turn."""

        return self._request(
            "POST",
            "/memories",
            {"messages": messages, "user_id": user_id, "metadata": metadata},
        )

    def search(self, *, query: str, user_id: str, limit: int) -> dict[str, Any]:
        """Execute official Mem0 v3 hybrid retrieval."""

        return self._request(
            "POST",
            "/search",
            {"query": query, "user_id": user_id, "limit": limit},
        )

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        last_error: Exception | None = None
        for attempt in range(HTTP_MAX_ATTEMPTS):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    value = json.loads(response.read().decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("mem0_response_is_not_an_object")
                return value
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < HTTP_MAX_ATTEMPTS - 1:
                    sleep(min(2**attempt, HTTP_BACKOFF_CAP_SECONDS))
        raise RuntimeError(f"mem0_http_request_failed:{type(last_error).__name__}")


def evaluate_mem0_same_control(
    root: Path,
    *,
    manifest_path: Path,
    source_commit: str,
    dataset_path: Path,
    ingestion_checkpoint_path: Path,
    answer_checkpoint_path: Path,
    server_url: str,
    max_ingest_workers: int = 2,
    max_answer_workers: int = 4,
    top_k: int = 20,
    max_output_tokens: int = 512,
) -> dict[str, Any]:
    """Run official Mem0 formation/retrieval and the frozen AgentLadder answer gate."""

    manifest = _read(manifest_path)
    verified_inputs = _verify_frozen_inputs(
        root,
        manifest=manifest,
        source_commit=source_commit,
        dataset_path=dataset_path,
    )
    agent_report = _read(
        root / "docs/reports/product/prompt-context-recovery-memory-agent-formal.json"
    )
    baseline_report = _read(
        root / "docs/reports/product/prompt-context-recovery-memory-baseline-formal.json"
    )
    turns, all_questions, dataset_stats = load_locomo(dataset_path)
    del turns
    questions = select_locomo_questions(
        all_questions, per_conversation=10, selection_offset=10
    )
    selected_hash = _stable_hash([question.case_id for question in questions])
    _require(selected_hash == SELECTED_CASE_IDS_SHA256, "selected_case_ids_changed")
    _require(
        selected_hash
        == agent_report["selection"]["selected_case_ids_sha256"]
        == baseline_report["selection"]["selected_case_ids_sha256"],
        "same_control_selection_mismatch",
    )
    health = Mem0HttpClient(server_url).health()
    _require(health.get("mem0_pr_head") == MEM0_PR_HEAD, "mem0_server_head_mismatch")
    _require(health.get("llm_model") == "deepseek-v4-flash", "mem0_llm_mismatch")
    _require(
        health.get("embedding_model") == EMBEDDING_MODEL,
        "mem0_embedding_model_mismatch",
    )
    _require(health.get("bm25_enabled") is True, "mem0_bm25_runtime_unavailable")
    _require(
        health.get("entity_runtime_available") is True,
        "mem0_entity_runtime_unavailable",
    )
    _require(
        health.get("qdrant_mode") == "service",
        "mem0_qdrant_service_required",
    )
    static_health = {
        key: health.get(key)
        for key in (
            "status",
            "mem0_pr_head",
            "llm_model",
            "embedding_model",
            "embedding_dims",
            "embedding_provider",
            "qdrant_mode",
            "bm25_enabled",
            "entity_runtime_available",
            "strict_extraction_json_boundary",
        )
    }
    controls = {
        "schema_version": SCHEMA_VERSION,
        "dataset_sha256": LOCOMO_DATA_SHA256,
        "selected_case_ids_sha256": selected_hash,
        "selection_offset": 10,
        "answer_model": MODEL,
        "answer_prompt_sha256": hashlib.sha256(
            ANSWER_PROMPT.encode("utf-8")
        ).hexdigest(),
        "extraction_model": "deepseek/deepseek-v4-flash",
        "extraction_max_output_tokens": 2400,
        "extraction_invalid_json_max_attempts": 3,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_runtime": "host-cached OpenAI-compatible local endpoint",
        "top_k": top_k,
        "max_output_tokens": max_output_tokens,
        "answer_temperature": 0.0,
        "mem0_pr_head": MEM0_PR_HEAD,
        # Dynamic retry counters are deliberately excluded so checkpoints keep
        # the same config hash across a resumed run.
        "server_health": static_health,
    }
    config_hash = _stable_hash(controls)
    user_prefix = f"locomo-v3-{config_hash[:12]}"
    official_turns = _load_official_ingestion_turns(dataset_path)
    ingestion_started = perf_counter()
    ingestion = _ingest_all(
        client=Mem0HttpClient(server_url),
        turns=official_turns,
        checkpoint_path=ingestion_checkpoint_path,
        config_hash=config_hash,
        user_prefix=user_prefix,
        max_workers=max_ingest_workers,
    )
    ingestion_duration_ms = int((perf_counter() - ingestion_started) * 1000)
    rows = _answer_all(
        root=root,
        client=Mem0HttpClient(server_url),
        questions=questions,
        checkpoint_path=answer_checkpoint_path,
        config_hash=config_hash,
        user_prefix=user_prefix,
        top_k=top_k,
        max_workers=max_answer_workers,
        max_output_tokens=max_output_tokens,
    )
    final_health = Mem0HttpClient(server_url).health()
    mem0 = _aggregate(rows)
    agent = agent_report["agent"]
    direct = baseline_report["systems"]["hybrid"]
    checks = {
        "all_source_hashes_and_commits_match": bool(verified_inputs),
        "deleted_branch_resolves_to_exact_pr_head": health.get("mem0_pr_head")
        == MEM0_PR_HEAD,
        "official_bm25_and_entity_runtime_green": health.get("bm25_enabled") is True
        and health.get("entity_runtime_available") is True,
        "qdrant_service_mode_avoids_embedded_entity_lock": health.get(
            "qdrant_mode"
        )
        == "service",
        "strict_extraction_json_failures_surface_for_http_retry": health.get(
            "strict_extraction_json_boundary"
        )
        is True,
        "same_frozen_100_case_ids": len(questions) == 100
        and selected_hash == SELECTED_CASE_IDS_SHA256,
        "same_answer_model": controls["answer_model"]
        == agent_report["controls"]["model"]
        == baseline_report["controls"]["model"],
        "same_direct_answer_prompt": controls["answer_prompt_sha256"]
        == baseline_report["controls"]["prompt_sha256"],
        "same_embedding_model": controls["embedding_model"]
        == agent_report["controls"]["embedding_model"],
        "same_top_k_generation_temperature_and_scorer": top_k == 20
        and max_output_tokens == 512
        and agent_report["controls"]["top_k"] == 20
        and agent_report["controls"]["max_output_tokens"] == 512
        and baseline_report["controls"]["top_k"] == 20
        and baseline_report["controls"]["max_output_tokens"] == 512,
        "official_mem0_formation_executed_for_every_turn": ingestion[
            "completed_turns"
        ]
        == len(official_turns),
        "all_100_cases_completed": mem0["completed"] == 100,
        "all_final_cases_error_free": mem0["errors"] == 0,
        "zero_strange_response_p0": mem0["strange_response_p0"] == 0,
    }
    passed = all(checks.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": STAGE_ID,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if passed else "failed",
        "passed": passed,
        "source": {
            "memory_benchmarks": {
                "repository": "https://github.com/mem0ai/memory-benchmarks",
                "commit": MEM0_BENCHMARK_COMMIT,
            },
            "mem0": {
                "repository": "https://github.com/mem0ai/mem0",
                "pull_request": "https://github.com/mem0ai/mem0/pull/4805",
                "pull_request_head": MEM0_PR_HEAD,
            },
            "locomo": {
                "repository": "https://github.com/snap-research/locomo",
                "commit": LOCOMO_COMMIT,
                "dataset_sha256": LOCOMO_DATA_SHA256,
                "license": LOCOMO_LICENSE,
            },
        },
        "selection": {
            "per_conversation": 10,
            "selection_offset": 10,
            "selected_questions": len(questions),
            "selected_case_ids_sha256": selected_hash,
        },
        "controls": controls,
        "config_sha256": config_hash,
        "dataset": dataset_stats,
        "ingestion": {
            **ingestion,
            "final_resume_process_duration_ms": ingestion_duration_ms,
            "end_to_end_duration_available": False,
            "duration_scope": "final checkpoint-resume process only; prior process durations were not persisted",
            "extraction_json_retries": int(
                final_health.get("extraction_json_retries", 0)
            ),
            "extraction_json_request_failures": int(
                final_health.get("extraction_json_request_failures", 0)
            ),
            "retry_counter_scope": "Mem0 adapter service lifetime, including the bounded preflight smoke and the formal checkpointed run",
            "http_max_attempts_per_turn": HTTP_MAX_ATTEMPTS,
            "http_backoff_cap_seconds": HTTP_BACKOFF_CAP_SECONDS,
            "provider_usage_telemetry_available": False,
            "conservative_cost_upper_bound_usd": round(
                len(official_turns)
                * (20_000 * 0.14 + 2_400 * 0.28)
                / 1_000_000,
                6,
            ),
            "cost_bound_assumption": "at most 20000 extraction input tokens and 2400 output tokens per one-turn call at the frozen DeepSeek rates; the cap, not observed usage, is used because the official SDK omits extraction usage",
            "checkpoint": _checkpoint_artifact(ingestion_checkpoint_path, root),
        },
        "systems": {
            "mem0_v3_pr4805": mem0,
            "klara_loop_memory_agent": _frozen_system(agent),
            "klara_direct_hybrid": _frozen_system(direct),
        },
        "comparison": {
            "agent_f1_delta_vs_mem0": round(
                float(agent["official_f1"]) - float(mem0["official_f1"]), 6
            ),
            "agent_recall_delta_vs_mem0": round(
                float(agent["evidence_recall_at_k"])
                - float(mem0["evidence_recall_at_k"]),
                6,
            ),
            "direct_f1_delta_vs_mem0": round(
                float(direct["official_f1"]) - float(mem0["official_f1"]), 6
            ),
            "frozen_same_control_agent_outperforms_mem0_on_f1": float(
                agent["official_f1"]
            )
            > float(mem0["official_f1"]),
            "frozen_same_control_agent_outperforms_mem0_on_recall": float(
                agent["evidence_recall_at_k"]
            )
            > float(mem0["evidence_recall_at_k"]),
            "general_mem0_superiority_claimed": False,
            "general_agentladder_superiority_claimed": False,
        },
        "rows": [_public_row(row) for row in rows],
        "answer_checkpoint": _checkpoint_artifact(answer_checkpoint_path, root),
        "verified_inputs": verified_inputs,
        "checks": checks,
        "harness_deviations": [
            "The deleted feat/v3-pipeline name is replaced only by its exact final official PR #4805 head SHA.",
            "The official benchmark wrapper drops timestamp and calls a removed user_id search argument; this adapter maps source time into created_at metadata and user scope into the v3 filters contract.",
            "Source dialogue IDs and turn order are observational metadata used only to compute deterministic evidence Recall@20 and chronological answer packing.",
            "The exact all-MiniLM-L6-v2 model runs in a host-cached OpenAI-compatible local endpoint; Mem0 calls it through the official OpenAI embedding provider to avoid downloading a duplicate Torch runtime into the container.",
            "Qdrant runs through the official v3 Qdrant adapter against a version-pinned service container; embedded mode is rejected because the exact PR head deep-copies the lazy entity-store config and conflicts with the local RocksDB lock.",
            "The official benchmark LLM answer prompt and LLM judge are replaced by AgentLadder's already frozen direct-baseline answer prompt and deterministic LoCoMo token-F1 scorer; the Agent retains its frozen tool-capability prompt.",
        ],
        "claim_boundary": [
            "This is a same-control comparison of the official OSS v3 PR head, not a Mem0 Platform score.",
            "A win on this frozen 100-question split is not a general superiority claim.",
            "No MEM1, BEAM, independent-model, blind-human, ChatGPT, or leaderboard result is inferred.",
            "No model training, HKU connection, upload, Slurm job, SFT, RL, or quantization occurred.",
        ],
    }


def run_live_smoke(*, server_url: str) -> dict[str, Any]:
    """Exercise real Mem0 formation and retrieval without touching benchmark state."""

    client = Mem0HttpClient(server_url)
    health = client.health()
    user_id = f"smoke-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    added = client.add(
        messages=[
            {
                "role": "user",
                "content": "Alice's benchmark-safe favorite color is cobalt blue.",
            }
        ],
        user_id=user_id,
        metadata={
            "locomo_dia_id": "smoke-D1:1",
            "conversation_turn_index": 0,
            "created_at": "2026-08-15T00:00:00+00:00",
        },
    )
    searched = client.search(
        query="What is Alice's benchmark-safe favorite color?",
        user_id=user_id,
        limit=5,
    )
    results = searched.get("results", [])
    passed = (
        health.get("mem0_pr_head") == MEM0_PR_HEAD
        and isinstance(added.get("results"), list)
        and isinstance(results, list)
        and any("cobalt" in _memory_text(item).casefold() for item in results)
    )
    return {
        "schema_version": "klara.mem0-comparable-smoke.v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "mem0_pr_head": health.get("mem0_pr_head"),
        "formation_result_count": len(added.get("results", [])),
        "retrieval_result_count": len(results),
        "contains_expected_fact": any(
            "cobalt" in _memory_text(item).casefold() for item in results
        ),
        "secrets_recorded": False,
    }


def render_mem0_report(report: dict[str, Any], *, language: str = "zh") -> str:
    """Render the machine-readable comparison without changing its claims."""

    zh = language == "zh"
    mem0 = report["systems"]["mem0_v3_pr4805"]
    agent = report["systems"]["klara_loop_memory_agent"]
    direct = report["systems"]["klara_direct_hybrid"]
    lines = [
        f"# {'Mem0 同控制复现' if zh else 'Mem0 Same-control Reproduction'}",
        "",
        (
            "语言：中文 | [English](./mem0-comparable-reproduction.en.md)"
            if zh
            else "Language: [Chinese](./mem0-comparable-reproduction.md) | English"
        ),
        "",
        f"- {'阶段' if zh else 'Stage'}: `{'通过' if report['passed'] and zh else 'PASS' if report['passed'] else '未通过' if zh else 'FAIL'}`",
        f"- Mem0 PR head: `{report['source']['mem0']['pull_request_head']}`",
        f"- {'冻结问题' if zh else 'Frozen questions'}: `{report['selection']['selected_questions']}`",
        "",
        f"## {'同控制成绩' if zh else 'Same-control Scores'}",
        "",
        "| System | F1 | EM | Recall@20 | Completed |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| Mem0 OSS v3 PR #4805 | {mem0['official_f1']:.6f} | {mem0['exact_match']:.6f} | {mem0['evidence_recall_at_k']:.6f} | {mem0['completed']}/{mem0['cases']} |",
        f"| KlaraLoop Agent | {agent['official_f1']:.6f} | {agent['exact_match']:.6f} | {agent['evidence_recall_at_k']:.6f} | {agent['completed']}/{agent['cases']} |",
        f"| Klara direct hybrid | {direct['official_f1']:.6f} | {direct['exact_match']:.6f} | {direct['evidence_recall_at_k']:.6f} | {direct['completed']}/{direct['cases']} |",
        "",
        f"## {'门槛' if zh else 'Gates'}",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        for name, passed in report["checks"].items()
    )
    lines.extend(
        [
            "",
            f"## {'适配偏差' if zh else 'Harness Deviations'}",
            "",
            *[f"- {item}" for item in report["harness_deviations"]],
            "",
            f"## {'声明边界' if zh else 'Claim Boundary'}",
            "",
            *[f"- {item}" for item in report["claim_boundary"]],
            "",
        ]
    )
    return "\n".join(lines)


def update_product_freeze_artifacts(
    root: Path,
    *,
    mem0_report: dict[str, Any],
    source_commit: str,
    python_tests_collected: int,
    python_tests_skipped: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Remove only the completed Mem0 blocker and preserve every other red gate."""

    _require(mem0_report["passed"] is True, "mem0_report_must_pass_before_reconcile")
    product = root / "docs/reports/product"
    readiness = deepcopy(_read(product / "agent-product-freeze-readiness.json"))
    ledger = deepcopy(_read(product / "completion-ledger.json"))
    readiness["evaluated_at"] = mem0_report["evaluated_at"]
    readiness["mandatory_blockers"] = [
        item
        for item in readiness["mandatory_blockers"]
        if item["id"] != "official-mem0-comparison"
    ]
    readiness["product_freeze_checks"][
        "official_mem0_same_control_comparison_green"
    ] = True
    readiness["memory"]["mem0_same_control"] = {
        "artifact": "docs/reports/product/mem0-comparable-reproduction.json",
        "official_f1": mem0_report["systems"]["mem0_v3_pr4805"]["official_f1"],
        "evidence_recall_at_20": mem0_report["systems"]["mem0_v3_pr4805"][
            "evidence_recall_at_k"
        ],
        "agent_f1_delta": mem0_report["comparison"]["agent_f1_delta_vs_mem0"],
        "agent_recall_delta": mem0_report["comparison"][
            "agent_recall_delta_vs_mem0"
        ],
        "general_superiority_claimed": False,
    }
    readiness["claims"].update(
        {
            "frozen_same_control_mem0_comparison_complete": True,
            "frozen_same_control_agent_outperforms_mem0_on_f1": mem0_report[
                "comparison"
            ]["frozen_same_control_agent_outperforms_mem0_on_f1"],
            "frozen_same_control_agent_outperforms_mem0_on_recall": mem0_report[
                "comparison"
            ]["frozen_same_control_agent_outperforms_mem0_on_recall"],
            "external_memory_competitor_superiority": False,
        }
    )
    followup_evidence = [
        item
        for item in readiness.setdefault("followup_evidence", [])
        if item.get("stage") != STAGE_ID
    ]
    followup_evidence.append(
        {
            "stage": STAGE_ID,
            "branch": STAGE_BRANCH,
            "source_commit": source_commit,
            "artifact": "docs/reports/product/mem0-comparable-reproduction.json",
            "schema_version": SCHEMA_VERSION,
            "passed": True,
        }
    )
    readiness["followup_evidence"] = followup_evidence
    readiness["stage_verification"]["python_tests_collected"] = (
        python_tests_collected
    )
    readiness["stage_verification"]["python_tests_skipped"] = python_tests_skipped
    readiness["agent_product_freeze_allowed"] = not readiness[
        "mandatory_blockers"
    ]
    readiness["model_training_allowed"] = readiness["agent_product_freeze_allowed"]
    readiness["status"] = (
        "agent_product_freeze_allowed"
        if readiness["agent_product_freeze_allowed"]
        else "stage_passed_product_freeze_blocked"
    )

    objectives = ledger["objectives"]
    by_id = {str(item["id"]): item for item in objectives}
    objective = {
        "id": STAGE_ID,
        "status": "passed",
        "branch": STAGE_BRANCH,
        "commit": source_commit,
        "commands": [
            "docker compose --env-file .env -f docker/mem0-comparable/compose.yaml up -d --build",
            "python -m klara.eval.mem0_comparable_live --smoke ...",
            "python -m klara.eval.mem0_comparable_live ...",
            "python -m pytest -q",
        ],
        "datasets": [
            "LoCoMo pinned offset-10 100-question validation split",
            "Mem0 official v3 PR #4805 final head",
        ],
        "evaluator_versions": [SCHEMA_VERSION],
        "artifacts": [
            "config/stages/mem0-comparable-reproduction.manifest.json",
            "docs/labs/mem0-comparable-reproduction.md",
            "docs/labs/mem0-comparable-reproduction.en.md",
            "docs/reports/product/mem0-comparable-reproduction.json",
            "docs/reports/product/mem0-comparable-reproduction.md",
            "docs/reports/product/mem0-comparable-reproduction.en.md",
        ],
        "evidence": {
            "passed": True,
            "official_mem0_pr_head": MEM0_PR_HEAD,
            "cases": mem0_report["systems"]["mem0_v3_pr4805"]["cases"],
        },
        "metrics": {
            "mem0_f1": mem0_report["systems"]["mem0_v3_pr4805"][
                "official_f1"
            ],
            "mem0_recall_at_20": mem0_report["systems"]["mem0_v3_pr4805"][
                "evidence_recall_at_k"
            ],
            "agent_f1_delta_vs_mem0": mem0_report["comparison"][
                "agent_f1_delta_vs_mem0"
            ],
        },
        "remaining_failures": [],
    }
    if STAGE_ID in by_id:
        by_id[STAGE_ID].update(objective)
    else:
        freeze_index = next(
            index
            for index, item in enumerate(objectives)
            if item["id"] == "agent-product-freeze"
        )
        objectives.insert(freeze_index, objective)
    blockers = [item["detail"] for item in readiness["mandatory_blockers"]]
    by_id["agent-product-freeze"]["remaining_failures"] = blockers
    by_id["agent-product-freeze"]["status"] = (
        "pending" if readiness["agent_product_freeze_allowed"] else "blocked_external"
    )
    by_id["agent-product-freeze"]["evidence"]["training_allowed"] = readiness[
        "model_training_allowed"
    ]
    benchmark = by_id["agent-product-benchmarks"]
    benchmark["metrics"].update(objective["metrics"])
    benchmark["remaining_failures"] = blockers + [
        item["detail"] for item in readiness["expansion_gaps"]
    ]
    ledger["updated_at"] = mem0_report["evaluated_at"]
    return readiness, ledger


def _ingest_all(
    *,
    client: Mem0HttpClient,
    turns: list[OfficialIngestionTurn],
    checkpoint_path: Path,
    config_hash: str,
    user_prefix: str,
    max_workers: int,
) -> dict[str, Any]:
    completed, extracted = _load_ingestion_checkpoint(
        checkpoint_path, config_hash=config_hash
    )
    grouped: dict[int, list[OfficialIngestionTurn]] = {}
    for turn in turns:
        grouped.setdefault(turn.conversation_index, []).append(turn)

    def ingest_conversation(items: list[OfficialIngestionTurn]) -> None:
        nonlocal extracted
        for turn in items:
            if turn.ingest_key in completed:
                continue
            result = client.add(
                messages=[{"role": turn.role, "content": turn.content}],
                user_id=f"{user_prefix}-conv{turn.conversation_index:02d}",
                metadata={
                    "locomo_dia_id": turn.dia_id,
                    "conversation_turn_index": turn.turn_index,
                    "created_at": turn.occurred_at
                    or "2026-01-01T00:00:00+00:00",
                    "source": "snap-research/locomo",
                    "adapter_ingest_key": turn.ingest_key,
                },
            )
            result_count = len(result.get("results", []))
            _append_checkpoint(
                checkpoint_path,
                {
                    "config_hash": config_hash,
                    "ingest_key": turn.ingest_key,
                    "extracted_memories": result_count,
                },
            )
            with _CHECKPOINT_LOCK:
                completed.add(turn.ingest_key)
                extracted += result_count

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(ingest_conversation, items)
            for _, items in sorted(grouped.items())
        ]
        for future in as_completed(futures):
            future.result()
    return {
        "turns": len(turns),
        "completed_turns": len(completed),
        "extracted_memories": extracted,
        "one_turn_chunks": True,
        "conversation_workers": max_workers,
    }


def _answer_all(
    *,
    root: Path,
    client: Mem0HttpClient,
    questions: list[LocomoQuestion],
    checkpoint_path: Path,
    config_hash: str,
    user_prefix: str,
    top_k: int,
    max_workers: int,
    max_output_tokens: int,
) -> list[dict[str, Any]]:
    completed = _load_answer_checkpoint(checkpoint_path, config_hash=config_hash)
    llm = _live_client(root, max_output_tokens=max_output_tokens)
    pending = [question for question in questions if question.case_id not in completed]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _answer_one,
                client=client,
                llm=llm,
                question=question,
                user_id=f"{user_prefix}-conv{question.conversation_index:02d}",
                config_hash=config_hash,
                top_k=top_k,
            ): question.case_id
            for question in pending
        }
        for future in as_completed(futures):
            row = future.result()
            completed[row["case_id"]] = row
            _append_checkpoint(checkpoint_path, row)
    return [
        completed[question.case_id]
        for question in questions
        if question.case_id in completed
    ]


def _answer_one(
    *,
    client: Mem0HttpClient,
    llm: Any,
    question: LocomoQuestion,
    user_id: str,
    config_hash: str,
    top_k: int,
) -> dict[str, Any]:
    started = perf_counter()
    prediction = ""
    prompt_tokens = 0
    completion_tokens = 0
    error: dict[str, Any] | None = None
    retrieval_started = perf_counter()
    raw_results: list[dict[str, Any]] = []
    try:
        response = client.search(query=question.question, user_id=user_id, limit=top_k)
        value = response.get("results", [])
        raw_results = value if isinstance(value, list) else []
        retrieval_latency_ms = int((perf_counter() - retrieval_started) * 1000)
        ordered = sorted(raw_results[:top_k], key=_turn_index)
        context = "\n".join(
            f"[{_memory_id(item)}; {_created_at(item)}] {_memory_text(item)}"
            for item in ordered
        )
        user_prompt = (
            f"Conversation memory:\n{context}\n\nQuestion: {question.question}"
        )
        model_response = llm.complete(
            system_prompt=ANSWER_PROMPT,
            messages=(KlaraMessage(role="user", content=user_prompt),),
            tools=(),
            model=MODEL,
            thinking_enabled=False,
        )
        prediction = model_response.content.strip()
        usage = model_response.usage or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
    except ModelCallError as exc:
        retrieval_latency_ms = int((perf_counter() - retrieval_started) * 1000)
        error = {"type": type(exc).__name__, "code": exc.code}
    except Exception as exc:  # pragma: no cover - defensive live boundary
        retrieval_latency_ms = int((perf_counter() - retrieval_started) * 1000)
        error = {"type": type(exc).__name__, "code": None}
    returned_ids = list(
        dict.fromkeys(
            source_id
            for item in raw_results[:top_k]
            for source_id in _source_ids(item)
        )
    )
    expected = set(question.evidence_ids)
    found = expected.intersection(returned_ids)
    return {
        "schema_version": SCHEMA_VERSION,
        "config_hash": config_hash,
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
        "returned_evidence_ids": returned_ids,
        "expected_evidence_ids": list(question.evidence_ids),
        "retrieved_memories": raw_results[:top_k],
        "context_items": min(len(raw_results), top_k),
        "model": MODEL,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "retrieval_latency_ms": retrieval_latency_ms,
        "latency_ms": int((perf_counter() - started) * 1000),
        "strange_response_p0": _strange_response(prediction),
        "error": error,
    }


def _load_official_ingestion_turns(path: Path) -> list[OfficialIngestionTurn]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    turns: list[OfficialIngestionTurn] = []
    for conversation_index, entry in enumerate(payload):
        conversation = entry["conversation"]
        speaker_a = str(conversation["speaker_a"])
        session_keys = sorted(
            (
                key
                for key, value in conversation.items()
                if key.startswith("session_")
                and not key.endswith("_date_time")
                and isinstance(value, list)
            ),
            key=lambda value: int(value.removeprefix("session_")),
        )
        turn_index = 0
        for session_key in session_keys:
            occurred_at = _locomo_iso(conversation.get(f"{session_key}_date_time"))
            for raw in conversation[session_key]:
                speaker = str(raw.get("speaker", ""))
                text = str(raw.get("text", "")).strip()
                query = str(raw.get("query", "")).strip()
                image = str(raw.get("blip_caption", "")).strip()
                if query and image:
                    photo = f"[Sharing image - query: {query}. The image shows: {image}]"
                elif query:
                    photo = f"[Sharing image - query for: {query}]"
                elif image:
                    photo = f"[Sharing image that shows: {image}]"
                else:
                    photo = ""
                if photo:
                    text = f"{text} {photo}" if text else photo
                dia_id = str(raw.get("dia_id", "")).strip()
                if not text or not dia_id:
                    continue
                turns.append(
                    OfficialIngestionTurn(
                        conversation_index=conversation_index,
                        turn_index=turn_index,
                        dia_id=dia_id,
                        role="user" if speaker == speaker_a else "assistant",
                        content=f"{speaker}: {text}",
                        occurred_at=occurred_at,
                    )
                )
                turn_index += 1
    return turns


def _locomo_iso(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC).isoformat()
        except ValueError:
            continue
    return None


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [int(row["latency_ms"]) for row in rows]
    retrieval_latencies = [int(row["retrieval_latency_ms"]) for row in rows]
    prompt_tokens = sum(int(row["prompt_tokens"]) for row in rows)
    completion_tokens = sum(int(row["completion_tokens"]) for row in rows)
    categories: dict[str, list[dict[str, Any]]] = {}
    errors = Counter()
    for row in rows:
        categories.setdefault(str(row["category"]), []).append(row)
        if row["error"]:
            errors[str(row["error"].get("code") or row["error"]["type"])] += 1
    return {
        "cases": len(rows),
        "completed": sum(row["error"] is None for row in rows),
        "errors": sum(errors.values()),
        "error_codes": dict(errors),
        "official_f1": _mean(row["official_f1"] for row in rows),
        "exact_match": _mean(float(row["exact_match"]) for row in rows),
        "evidence_recall_at_k": _mean(
            row["evidence_recall_at_k"] for row in rows
        ),
        "category_f1": {
            category: _mean(row["official_f1"] for row in values)
            for category, values in sorted(categories.items())
        },
        "average_context_items": _mean(row["context_items"] for row in rows),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "average_total_tokens": (prompt_tokens + completion_tokens) / len(rows)
        if rows
        else 0.0,
        "p50_retrieval_latency_ms": median(retrieval_latencies)
        if retrieval_latencies
        else 0.0,
        "p95_retrieval_latency_ms": _percentile(retrieval_latencies, 0.95),
        "p50_latency_ms": median(latencies) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "estimated_answer_api_cost_usd": round(
            (prompt_tokens * 0.14 + completion_tokens * 0.28) / 1_000_000, 8
        ),
        "extraction_api_cost_available": False,
        "strange_response_p0": sum(bool(row["strange_response_p0"]) for row in rows),
    }


def _frozen_system(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "cases": int(value["cases"]),
        "completed": int(value["completed"]),
        "official_f1": float(value["official_f1"]),
        "exact_match": float(value["exact_match"]),
        "evidence_recall_at_k": float(value["evidence_recall_at_k"]),
    }


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "category": row["category"],
        "official_f1": row["official_f1"],
        "exact_match": row["exact_match"],
        "evidence_recall_at_k": row["evidence_recall_at_k"],
        "context_items": row["context_items"],
        "answer_sha256": row["answer_sha256"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "retrieval_latency_ms": row["retrieval_latency_ms"],
        "latency_ms": row["latency_ms"],
        "strange_response_p0": row["strange_response_p0"],
        "error": row["error"],
    }


def _verify_frozen_inputs(
    root: Path,
    *,
    manifest: dict[str, Any],
    source_commit: str,
    dataset_path: Path,
) -> list[dict[str, Any]]:
    _require(manifest["parent_commit"] == source_commit, "parent_commit_mismatch")
    benchmark_checkout = root / ".tmp/public-benchmarks/mem0"
    source_inspection = inspect_public_source(
        benchmark_checkout,
        expected_commit=MEM0_BENCHMARK_COMMIT,
        required_paths=(
            "docker/mem0/requirements.txt",
            "benchmarks/locomo/run.py",
            "LICENSE",
        ),
    )
    _require(source_inspection["passed"], "memory_benchmarks_source_mismatch")
    candidates = [
        (
            dataset_path,
            manifest["sources"]["locomo"]["dataset_sha256"],
        ),
        (
            root
            / "docs/reports/product/prompt-context-recovery-memory-agent-formal.json",
            manifest["sources"]["frozen_agent_report"]["sha256"],
        ),
        (
            root
            / "docs/reports/product/prompt-context-recovery-memory-baseline-formal.json",
            manifest["sources"]["frozen_direct_baseline_report"]["sha256"],
        ),
        (
            root / "docs/reports/product/mem0-reproduction.json",
            manifest["sources"]["historical_blocker_report"]["sha256"],
        ),
        (
            benchmark_checkout / "docker/mem0/requirements.txt",
            manifest["sources"]["memory_benchmarks"]["requirements_sha256"],
        ),
    ]
    verified = []
    for path, expected in candidates:
        actual = _sha256(path)
        _require(actual == expected, f"frozen_input_hash_mismatch:{path.name}")
        verified.append(
            {"path": _safe_relative(path, root), "sha256": actual, "verified": True}
        )
    return verified


def _load_ingestion_checkpoint(
    path: Path, *, config_hash: str
) -> tuple[set[str], int]:
    completed: set[str] = set()
    extracted = 0
    for row in _checkpoint_rows(path, config_hash=config_hash):
        key = row.get("ingest_key")
        if isinstance(key, str):
            completed.add(key)
            extracted += int(row.get("extracted_memories", 0))
    return completed, extracted


def _load_answer_checkpoint(
    path: Path, *, config_hash: str
) -> dict[str, dict[str, Any]]:
    return {
        str(row["case_id"]): row
        for row in _checkpoint_rows(path, config_hash=config_hash)
        if isinstance(row.get("case_id"), str) and row.get("error") is None
    }


def _checkpoint_rows(path: Path, *, config_hash: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("config_hash") == config_hash:
            rows.append(row)
    return rows


def _append_checkpoint(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _CHECKPOINT_LOCK:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _checkpoint_artifact(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": _safe_relative(path, root),
        "tracked_in_git": False,
        "contains_public_dataset_text": True,
        "sha256": _sha256(path) if path.is_file() else None,
    }


def _memory_text(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("memory", item.get("data", "")))


def _memory_id(item: dict[str, Any]) -> str:
    return str(item.get("id", "memory"))


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("metadata", {})
    return value if isinstance(value, dict) else {}


def _created_at(item: dict[str, Any]) -> str:
    return str(item.get("created_at") or _metadata(item).get("created_at") or "unknown")


def _turn_index(item: dict[str, Any]) -> int:
    try:
        return int(_metadata(item).get("conversation_turn_index", 1_000_000))
    except (TypeError, ValueError):
        return 1_000_000


def _source_ids(item: dict[str, Any]) -> list[str]:
    value = _metadata(item).get("locomo_dia_id")
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _strange_response(value: str) -> str | None:
    compact = value.strip()
    if not compact:
        return "empty_answer"
    lowered = compact.casefold()
    if "<|dsml|" in lowered or "tool_calls" in lowered:
        return "internal_tool_protocol_leak"
    if len(compact) > 2_000:
        return "answer_exceeds_2000_chars"
    return None


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile)))
    return float(ordered[index])


def _mean(values: Iterable[float]) -> float:
    collected = list(values)
    return round(mean(collected), 6) if collected else 0.0


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "[external-path]"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the live smoke or the complete frozen Mem0 comparison."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--server-url", default="http://localhost:18888")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--ingestion-checkpoint", type=Path)
    parser.add_argument("--answer-checkpoint", type=Path)
    parser.add_argument("--max-ingest-workers", type=int, default=2)
    parser.add_argument("--max-answer-workers", type=int, default=4)
    parser.add_argument("--python-tests-collected", type=int, default=0)
    parser.add_argument("--python-tests-skipped", type=int, default=0)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.smoke:
        result = run_live_smoke(server_url=args.server_url)
        output = root / ".tmp/mem0-comparable/smoke.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["passed"] else 1
    required = {
        "manifest": args.manifest,
        "source_commit": args.source_commit,
        "dataset": args.dataset,
        "ingestion_checkpoint": args.ingestion_checkpoint,
        "answer_checkpoint": args.answer_checkpoint,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        parser.error("missing required full-run arguments: " + ", ".join(missing))
    report = evaluate_mem0_same_control(
        root,
        manifest_path=args.manifest.resolve(),
        source_commit=str(args.source_commit),
        dataset_path=args.dataset.resolve(),
        ingestion_checkpoint_path=args.ingestion_checkpoint.resolve(),
        answer_checkpoint_path=args.answer_checkpoint.resolve(),
        server_url=args.server_url,
        max_ingest_workers=args.max_ingest_workers,
        max_answer_workers=args.max_answer_workers,
    )
    product = root / "docs/reports/product"
    product.mkdir(parents=True, exist_ok=True)
    (product / "mem0-comparable-reproduction.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (product / "mem0-comparable-reproduction.md").write_text(
        render_mem0_report(report), encoding="utf-8", newline="\n"
    )
    (product / "mem0-comparable-reproduction.en.md").write_text(
        render_mem0_report(report, language="en"), encoding="utf-8", newline="\n"
    )
    if report["passed"]:
        readiness, ledger = update_product_freeze_artifacts(
            root,
            mem0_report=report,
            source_commit=str(args.source_commit),
            python_tests_collected=args.python_tests_collected,
            python_tests_skipped=args.python_tests_skipped,
        )
        (product / "agent-product-freeze-readiness.json").write_text(
            json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        (product / "agent-product-freeze-readiness.md").write_text(
            render_report(readiness), encoding="utf-8", newline="\n"
        )
        (product / "agent-product-freeze-readiness.en.md").write_text(
            render_report(readiness, language="en"),
            encoding="utf-8",
            newline="\n",
        )
        (product / "completion-ledger.json").write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        (product / "completion-ledger.md").write_text(
            render_ledger(ledger), encoding="utf-8", newline="\n"
        )
        (product / "completion-ledger.en.md").write_text(
            render_ledger(ledger, language="en"),
            encoding="utf-8",
            newline="\n",
        )
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "mem0": report["systems"]["mem0_v3_pr4805"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
