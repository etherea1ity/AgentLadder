"""Inspect official memory competitor implementations without claiming parity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from klara.eval.public_memory import inspect_public_source


SCHEMA_VERSION = "klara.public-memory-competitor-contract.v1"
MEM0_COMMIT = "4b61c5d31b9c668a12b4f5e78064248a02c82d2b"
MEM1_COMMIT = "2609aef4e7c46d8d0c0f06b9312bc4b4abe04b9d"
BEAM_COMMIT = "3e12035532eb85768f1a7cd779832b650c4b2ef9"


def run_memory_competitor_contracts(
    *,
    mem0_checkout: Path,
    mem1_checkout: Path,
    beam_checkout: Path,
) -> dict[str, Any]:
    """Return honest readiness facts for Mem0, MEM1, and BEAM."""

    mem0 = _mem0_contract(mem0_checkout)
    mem1 = _mem1_contract(mem1_checkout)
    beam = _beam_contract(beam_checkout)
    checks = {
        "all_sources_pinned": all(
            item["source_inspection"]["passed"] for item in (mem0, mem1, beam)
        ),
        "all_licenses_present": all(item["license_present"] for item in (mem0, mem1, beam)),
        "no_competitor_score_claimed": all(
            item["score_status"] == "not_claimed" for item in (mem0, mem1, beam)
        ),
        "comparability_requirements_declared": all(
            bool(item["requirements_for_comparable_score"])
            for item in (mem0, mem1, beam)
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "interpretation": (
            "PASS proves pinned source, license, and execution contracts only. "
            "Mem0, MEM1, and BEAM scores remain unclaimed until their official "
            "pipelines run under frozen models, data, budgets, and graders."
        ),
        "systems": {"mem0": mem0, "mem1": mem1, "beam": beam},
        "checks": checks,
        "passed": all(checks.values()),
    }


def _mem0_contract(checkout: Path) -> dict[str, Any]:
    source = inspect_public_source(
        checkout,
        expected_commit=MEM0_COMMIT,
        required_paths=(
            "LICENSE",
            "README.md",
            "docker-compose.yml",
            "benchmarks/locomo/run.py",
            "benchmarks/longmemeval/run.py",
            "benchmarks/beam/run.py",
        ),
    )
    readme = (checkout / "README.md").read_text(encoding="utf-8")
    return {
        "system": "Mem0 official memory-benchmarks",
        "source": "https://github.com/mem0ai/memory-benchmarks",
        "commit": MEM0_COMMIT,
        "license": "Apache-2.0",
        "license_present": "Apache License" in (checkout / "LICENSE").read_text(encoding="utf-8"),
        "source_inspection": source,
        "official_benchmarks": ["LoCoMo", "LongMemEval", "BEAM"],
        "runtime_contract": {
            "self_hosted_backend": "Mem0 OSS + Qdrant through Docker Compose",
            "cloud_backend": "Mem0 API key",
            "model_sensitive_components": ["fact extraction", "embeddings", "answerer", "judge"],
            "declares_docker": "Docker" in readme and "Qdrant" in readme,
        },
        "execution_status": "not_executed",
        "score_status": "not_claimed",
        "requirements_for_comparable_score": [
            "same LoCoMo/LongMemEval/BEAM split and top-k",
            "same extraction and embedding models",
            "same answerer and judge models",
            "same generation limits and declared paid budget",
            "official Mem0 raw result artifacts",
        ],
    }


def _mem1_contract(checkout: Path) -> dict[str, Any]:
    source = inspect_public_source(
        checkout,
        expected_commit=MEM1_COMMIT,
        required_paths=(
            "LICENSE",
            "README.md",
            "Mem1/inference/start_vllm.sh",
            "Mem1/inference/generate_rollout.py",
            "Mem1/inference/eval.py",
            "examples/demo.jsonl",
        ),
    )
    readme = (checkout / "README.md").read_text(encoding="utf-8")
    demo_rows = _jsonl_count(checkout / "examples" / "demo.jsonl")
    return {
        "system": "MEM1 official learned constant-memory agent",
        "source": "https://github.com/MIT-MI/MEM1",
        "commit": MEM1_COMMIT,
        "license": "MIT",
        "license_present": "MIT License" in (checkout / "LICENSE").read_text(encoding="utf-8"),
        "source_inspection": source,
        "released_model": "Mem-Lab/Qwen2.5-7B-RL-RAG-Q2-EM-Release",
        "demo_trajectory_rows": demo_rows,
        "runtime_contract": {
            "requires_vllm": "vllm" in readme.casefold(),
            "requires_gpu_retriever": "faiss-gpu" in readme.casefold(),
            "evaluation_task": "multi-objective QA trajectory exact/model-estimated match",
            "not_drop_in_retrieval_baseline": True,
        },
        "execution_status": "not_executed",
        "score_status": "not_claimed",
        "requirements_for_comparable_score": [
            "serve the official 7B checkpoint through the pinned vLLM environment",
            "serve the official retriever and use its released evaluation data",
            "run official rollout and eval scripts on GPU",
            "compare task success and memory/token use on the same objectives",
            "do not compare its QA score directly with Klara LoCoMo retrieval Recall@5",
        ],
    }


def _beam_contract(checkout: Path) -> dict[str, Any]:
    source = inspect_public_source(
        checkout,
        expected_commit=BEAM_COMMIT,
        required_paths=(
            "LICENSE",
            "README.md",
            "requirements.txt",
            "src/evaluation/run_evaluation.py",
            "src/evaluation/compute_metrics.py",
        ),
    )
    readme = (checkout / "README.md").read_text(encoding="utf-8")
    return {
        "system": "BEAM long-term-memory benchmark",
        "source": "https://github.com/mohammadtavakoli78/BEAM",
        "commit": BEAM_COMMIT,
        "license": "MIT code; dataset terms must be checked at acquisition",
        "license_present": "MIT License" in (checkout / "LICENSE").read_text(encoding="utf-8"),
        "source_inspection": source,
        "published_contract": {
            "conversations": 100,
            "validated_questions": 2000,
            "context_scales": ["128K", "500K", "1M", "10M"],
            "readme_declares_statistics": "2,000 validated questions" in readme,
        },
        "execution_status": "not_executed",
        "score_status": "not_claimed",
        "requirements_for_comparable_score": [
            "download a licensed official BEAM dataset snapshot with file hashes",
            "freeze context scale, question subset, prompt, answer model, and judge",
            "run Klara and competitors on identical histories and limits",
            "retain per-capability official evaluation outputs",
        ],
    }


def _jsonl_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
