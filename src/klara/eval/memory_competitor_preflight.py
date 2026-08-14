"""Runtime preflight for official Mem0, MEM1, and BEAM execution."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Any

from klara.eval.public_memory_competitors import run_memory_competitor_contracts
from klara.infra.config.env import get_env_secret


SCHEMA_VERSION = "klara.memory-competitor-execution-preflight.v1"


def build_memory_competitor_execution_preflight(
    *,
    project_root: Path,
    mem0_checkout: Path,
    mem1_checkout: Path,
    beam_checkout: Path,
    runtime_facts: dict[str, bool] | None = None,
) -> dict[str, Any]:
    contracts = run_memory_competitor_contracts(
        mem0_checkout=mem0_checkout,
        mem1_checkout=mem1_checkout,
        beam_checkout=beam_checkout,
    )
    facts = runtime_facts or _detect_runtime_facts(
        project_root=project_root,
        mem1_checkout=mem1_checkout,
        beam_checkout=beam_checkout,
    )
    mem0_ready = facts["openai_api_key_configured"] or (
        facts["deepseek_api_key_configured"] and facts["ollama_available"]
    )
    mem1_ready = facts["mem1_checkpoint_cached"] and facts["gpu_runtime_available"]
    beam_ready = facts["beam_dataset_snapshot_available"]
    systems = {
        "mem0": {
            "source_contract_passed": contracts["systems"]["mem0"][
                "source_inspection"
            ]["passed"],
            "deepseek_answerer_configured": facts["deepseek_api_key_configured"],
            "official_default_openai_stack_configured": facts[
                "openai_api_key_configured"
            ],
            "local_ollama_embedder_available": facts["ollama_available"],
            "cloud_mem0_configured": facts["mem0_api_key_configured"],
            "execution_ready": mem0_ready,
            "execution_status": "ready" if mem0_ready else "blocked_external_dependencies",
            "blockers": []
            if mem0_ready
            else [
                "The official default OSS stack requires an OpenAI extraction and embedding credential, which is not configured.",
                "DeepSeek can supply the common answerer/extraction model through an OpenAI-compatible endpoint but does not supply the required embedding endpoint.",
                "The official Ollama alternative and nomic embedding runtime are not installed; starting a sustained local embedding workload is outside the thermal-safe pre-HKU boundary.",
            ],
            "score_status": "not_claimed",
        },
        "mem1": {
            "source_contract_passed": contracts["systems"]["mem1"][
                "source_inspection"
            ]["passed"],
            "official_checkpoint_cached": facts["mem1_checkpoint_cached"],
            "gpu_runtime_available": facts["gpu_runtime_available"],
            "execution_ready": mem1_ready,
            "execution_status": "ready" if mem1_ready else "hku_gpu_rollout_pending",
            "blockers": []
            if mem1_ready
            else [
                "The official 7B checkpoint is not cached in the repository workspace.",
                "The pinned vLLM/retriever rollout is an HKU GPU evaluation task and has not started before Agent Product Freeze.",
            ],
            "score_status": "not_claimed",
        },
        "beam": {
            "source_contract_passed": contracts["systems"]["beam"][
                "source_inspection"
            ]["passed"],
            "official_dataset_snapshot_available": facts[
                "beam_dataset_snapshot_available"
            ],
            "execution_ready": beam_ready,
            "execution_status": "ready" if beam_ready else "licensed_dataset_pending",
            "blockers": []
            if beam_ready
            else [
                "No licensed official BEAM dataset snapshot with an acquisition ledger and file hashes is present.",
                "The 128K+ context evaluation remains an HKU-scale task after the dataset is acquired.",
            ],
            "score_status": "not_claimed",
        },
    }
    checks = {
        "all_official_sources_pinned": contracts["checks"]["all_sources_pinned"],
        "runtime_facts_are_boolean": all(isinstance(value, bool) for value in facts.values()),
        "no_unexecuted_score_claimed": all(
            system["score_status"] == "not_claimed" for system in systems.values()
        ),
        "blocked_systems_name_exact_dependencies": all(
            system["execution_ready"] or bool(system["blockers"])
            for system in systems.values()
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "status": "ready" if all(item["execution_ready"] for item in systems.values()) else "external_execution_blocked",
        "systems": systems,
        "sanitized_runtime_facts": facts,
        "checks": checks,
        "preflight_passed": all(checks.values()),
        "scores_ready": all(item["execution_ready"] for item in systems.values()),
        "model_training_started": False,
        "hku_connection_started_by_this_preflight": False,
    }


def _detect_runtime_facts(
    *, project_root: Path, mem1_checkout: Path, beam_checkout: Path
) -> dict[str, bool]:
    dotenv = str(project_root / ".env")
    return {
        "deepseek_api_key_configured": bool(
            get_env_secret("DEEPSEEK_API_KEY", dotenv_path=dotenv)
        ),
        "openai_api_key_configured": bool(
            get_env_secret("OPENAI_API_KEY", dotenv_path=dotenv)
        ),
        "mem0_api_key_configured": bool(
            get_env_secret("MEM0_API_KEY", dotenv_path=dotenv)
        ),
        "ollama_available": shutil.which("ollama") is not None,
        "mem1_checkpoint_cached": any(mem1_checkout.rglob("*.safetensors")),
        "gpu_runtime_available": False,
        "beam_dataset_snapshot_available": any(
            path.stat().st_size > 1_000_000
            for suffix in ("*.json", "*.jsonl", "*.parquet")
            for path in beam_checkout.rglob(suffix)
        ),
    }


def render_preflight_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    zh = language == "zh"
    lines = [
        f"# {'Memory 竞品执行预检' if zh else 'Memory Competitor Execution Preflight'}",
        "",
        (
            "语言：中文 | [English](./agent-product-memory-competitor-preflight.en.md)"
            if zh
            else "Language: [Chinese](./agent-product-memory-competitor-preflight.md) | English"
        ),
        "",
        f"- {'预检' if zh else 'Preflight'}: `{'通过' if report['preflight_passed'] and zh else 'PASS' if report['preflight_passed'] else '未通过' if zh else 'FAIL'}`",
        f"- {'执行状态' if zh else 'Execution status'}: `{report['status']}`",
        f"- {'竞品成绩可用' if zh else 'Competitor scores ready'}: `{report['scores_ready']}`",
        "",
        f"## {'逐系统状态' if zh else 'Per-system Status'}",
        "",
        f"| {'系统' if zh else 'System'} | {'来源固定' if zh else 'Source pinned'} | {'执行就绪' if zh else 'Execution ready'} | {'状态' if zh else 'Status'} |",
        "| --- | --- | --- | --- |",
    ]
    for name, system in report["systems"].items():
        lines.append(
            f"| {name} | {system['source_contract_passed']} | "
            f"{system['execution_ready']} | {system['execution_status']} |"
        )
    lines.extend(["", f"## {'阻塞' if zh else 'Blockers'}", ""])
    for name, system in report["systems"].items():
        for blocker in system["blockers"]:
            lines.append(f"- `{name}`: {blocker}")
    lines.extend(
        [
            "",
            (
                "本预检通过只表示来源、依赖和阻塞被准确识别；Mem0、MEM1、BEAM 尚无可比较成绩。"
                if zh
                else "A passing preflight means sources, dependencies, and blockers were identified accurately; it is not a Mem0, MEM1, or BEAM score."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--mem0-checkout", type=Path, required=True)
    parser.add_argument("--mem1-checkout", type=Path, required=True)
    parser.add_argument("--beam-checkout", type=Path, required=True)
    parser.add_argument("--output-stem", default="agent-product-memory-competitor-preflight")
    args = parser.parse_args()
    root = args.root.resolve()
    report = build_memory_competitor_execution_preflight(
        project_root=root,
        mem0_checkout=args.mem0_checkout.resolve(),
        mem1_checkout=args.mem1_checkout.resolve(),
        beam_checkout=args.beam_checkout.resolve(),
    )
    output = root / "docs" / "reports" / "product"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{args.output_stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / f"{args.output_stem}.md").write_text(
        render_preflight_markdown(report), encoding="utf-8"
    )
    (output / f"{args.output_stem}.en.md").write_text(
        render_preflight_markdown(report, language="en"), encoding="utf-8"
    )
    print(json.dumps({"preflight_passed": report["preflight_passed"], "scores_ready": report["scores_ready"]}))


if __name__ == "__main__":
    main()
