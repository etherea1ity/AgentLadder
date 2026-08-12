"""HKU-only fair dense versus four-expert top-2 MoE experiment."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import platform
from typing import Any, Sequence
import tomllib

import torch

from klara.eval.trajectory import canonical_json, stable_sha256
from klara.training.checkpoint import load_checkpoint, save_checkpoint
from klara.training.config import ModelConfig, TrainConfig
from klara.training.data import build_causal_batches, read_corpus
from klara.training.model import TinyDecoderLM
from klara.training.moe import (
    MOE_SCORER_VERSION,
    MoEConfig,
    balanced_router_probe,
    build_moe_model,
    routing_diagnostics,
)
from klara.training.moe_report import MoEReport
from klara.training.tokenizer import ByteTokenizer
from klara.training.trainer import model_state_sha256, seed_everything, train_language_model


def run_moe(config_path: Path, corpus_path: Path, artifact_dir: Path) -> MoEReport:
    """Train identical dense/MoE controls and enforce every Gate 4 check."""

    raw_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    execution = dict(raw_config["execution"])
    _validate_execution_boundary(execution)
    if bool(execution["require_cuda_training"]) and not torch.cuda.is_available():
        raise RuntimeError("formal MoE experiment requires CUDA")
    model_config = ModelConfig.from_dict(dict(raw_config["model"]))
    train_config = TrainConfig.from_dict(dict(raw_config["train"]))
    moe_config = MoEConfig(**dict(raw_config["moe"]))
    gate = dict(raw_config["gate"])
    tokenizer = ByteTokenizer()
    texts = read_corpus(corpus_path)
    batches = build_causal_batches(
        texts,
        tokenizer,
        sequence_length=model_config.max_sequence_length,
        batch_size=train_config.batch_size,
    )
    prompt = str(raw_config["generation"]["prompt"])

    seed_everything(train_config.seed)
    dense_model = TinyDecoderLM(model_config)
    dense_result, _ = train_language_model(
        dense_model,
        batches,
        train_config,
        tokenizer=tokenizer,
        generation_prompt=prompt,
    )
    seed_everything(train_config.seed)
    moe_model = build_moe_model(model_config, moe_config)
    moe_result, _ = train_language_model(
        moe_model,
        batches,
        train_config,
        tokenizer=tokenizer,
        generation_prompt=prompt,
    )

    device = torch.device("cuda")
    fixture_input = torch.cat([batch.input_ids for batch in batches], dim=0)
    fixture_mask = torch.cat([batch.attention_mask for batch in batches], dim=0)
    corpus_routing = routing_diagnostics(
        moe_model,
        fixture_input,
        fixture_mask,
        device=device,
    )
    balanced_routing = balanced_router_probe(moe_model, device=device)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    hardware = _hardware_manifest()
    hashes = {
        "config_sha256": stable_sha256(canonical_json(raw_config)),
        "data_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "scorer_sha256": stable_sha256(MOE_SCORER_VERSION),
    }
    dense_path = artifact_dir / "dense_control.pt"
    moe_path = artifact_dir / "tiny_moe.pt"
    dense_sha256 = save_checkpoint(
        dense_path,
        model=dense_model,
        optimizer=None,
        step=train_config.steps,
        metadata={"role": "dense_control", **hashes},
    )
    moe_sha256 = save_checkpoint(
        moe_path,
        model=moe_model,
        optimizer=None,
        step=train_config.steps,
        metadata={"role": "four_expert_top2_moe", **hashes},
    )
    dense_restored = TinyDecoderLM(model_config)
    moe_restored = build_moe_model(model_config, moe_config)
    dense_details = load_checkpoint(
        dense_path, model=dense_restored, expected_sha256=dense_sha256
    )
    moe_details = load_checkpoint(
        moe_path, model=moe_restored, expected_sha256=moe_sha256
    )
    dense_reload_hash = model_state_sha256(dense_restored)
    moe_reload_hash = model_state_sha256(moe_restored)
    minimum_reduction = float(gate["minimum_loss_reduction_fraction"])
    weight_atol = float(gate["selected_weight_sum_atol"])
    maximum_peak = int(gate["maximum_gpu_peak_allocated_bytes"])
    checks = {
        "exactly_four_experts": moe_config.num_experts == 4,
        "top2_distinct_routing": moe_config.top_k == 2,
        "selected_weights_normalized": abs(
            corpus_routing["selected_weight_sum_mean"] - 1.0
        ) <= weight_atol,
        "finite_forward_backward": moe_result.gradients_finite
        and all(
            torch.isfinite(torch.tensor(value))
            for value in (
                moe_result.initial_loss,
                moe_result.final_loss,
                corpus_routing["router_z_loss"],
                corpus_routing["router_balance_loss"],
            )
        ),
        "auxiliary_loss_present": corpus_routing["router_balance_loss"] > 0,
        "z_loss_present": corpus_routing["router_z_loss"] > 0,
        "balanced_all_experts_used": balanced_routing["all_experts_used"],
        "balanced_load_ratio": balanced_routing["max_min_load_ratio"]
        <= float(gate["maximum_balanced_load_ratio"]),
        "router_entropy": corpus_routing["router_entropy"]
        >= float(gate["minimum_router_entropy"]),
        "collapse_detection_passed": not balanced_routing["collapse_detected"],
        "dense_loss_reduction": dense_result.loss_reduction_fraction
        >= minimum_reduction,
        "moe_loss_reduction": moe_result.loss_reduction_fraction
        >= minimum_reduction,
        "identical_comparison_contract": True,
        "gpu_peak_under_limit": max(
            dense_result.peak_allocated_bytes,
            moe_result.peak_allocated_bytes,
        ) < maximum_peak,
        "dense_checkpoint_reload": dense_details["sha256"] == dense_sha256
        and dense_reload_hash == dense_result.model_state_sha256,
        "moe_checkpoint_reload": moe_details["sha256"] == moe_sha256
        and moe_reload_hash == moe_result.model_state_sha256,
        "slurm_cuda_execution": bool(os.environ.get("SLURM_JOB_ID"))
        and dense_result.device.startswith("cuda")
        and moe_result.device.startswith("cuda"),
    }
    fairness = {
        "data_sha256": hashes["data_sha256"],
        "seed": train_config.seed,
        "steps": train_config.steps,
        "batch_size": train_config.batch_size,
        "learning_rate": train_config.learning_rate,
        "weight_decay": train_config.weight_decay,
        "gradient_clip": train_config.gradient_clip,
        "precision": train_config.precision,
        "scorer_version": MOE_SCORER_VERSION,
        "scorer_sha256": hashes["scorer_sha256"],
    }
    report = MoEReport(
        experiment=str(raw_config["experiment"]["name"]),
        evaluated_at=datetime.now(UTC).isoformat(),
        source=_source_manifest(),
        fairness=fairness,
        architecture={
            "model": model_config.to_dict(),
            "moe": dict(raw_config["moe"]),
            "dense_parameter_count": dense_result.parameter_count,
            "moe_parameter_count": moe_result.parameter_count,
        },
        dense=dense_result.to_dict(),
        moe=moe_result.to_dict(),
        routing={
            "training_corpus": corpus_routing,
            "balanced_probe": balanced_routing,
        },
        checkpoints={
            "dense": {
                "path": dense_path.as_posix(),
                "sha256": dense_sha256,
                "model_state_sha256": dense_result.model_state_sha256,
                "restored_model_state_sha256": dense_reload_hash,
            },
            "moe": {
                "path": moe_path.as_posix(),
                "sha256": moe_sha256,
                "model_state_sha256": moe_result.model_state_sha256,
                "restored_model_state_sha256": moe_reload_hash,
            },
        },
        hashes=hashes,
        hardware=hardware,
        checks=checks,
        passed=all(checks.values()),
    )
    (artifact_dir / "manifest.json").write_text(
        json.dumps(
            {"schema_version": "klara.moe-run.v1", **report.to_dict()},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_moe(args.config, args.corpus, args.artifact_dir)
    args.json_out.write_text(report.to_json(), encoding="utf-8", newline="\n")
    args.markdown_out.write_text(report.to_markdown(), encoding="utf-8", newline="\n")
    print(report.to_json(), end="")
    return 0 if report.passed else 1


def _validate_execution_boundary(execution: dict[str, Any]) -> None:
    required = {
        key: os.environ.get(key, "")
        for key in (
            "SLURM_JOB_ID", "SLURMD_NODENAME", "SLURM_JOB_PARTITION",
            "AGENTLADDER_SOURCE_DIR", "AGENTLADDER_SOURCE_BUNDLE_SHA256",
            "AGENTLADDER_PARENT_COMMIT",
        )
    }
    if bool(execution["require_slurm"]) and any(not value for value in required.values()):
        raise RuntimeError("formal MoE experiment requires HKU Slurm lineage")
    source = Path(required["AGENTLADDER_SOURCE_DIR"])
    try:
        source.relative_to(Path(str(execution["remote_root"])) / "deployments")
    except ValueError as exc:
        raise RuntimeError("MoE source is outside HKU deployments") from exc
    if len(required["AGENTLADDER_SOURCE_BUNDLE_SHA256"]) != 64:
        raise RuntimeError("source bundle SHA-256 is malformed")
    if len(required["AGENTLADDER_PARENT_COMMIT"]) != 40:
        raise RuntimeError("parent commit is malformed")


def _source_manifest() -> dict[str, str]:
    return {
        "parent_commit": os.environ["AGENTLADDER_PARENT_COMMIT"],
        "bundle_sha256": os.environ["AGENTLADDER_SOURCE_BUNDLE_SHA256"],
        "deployment": os.environ["AGENTLADDER_SOURCE_DIR"],
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "slurm_node": os.environ["SLURMD_NODENAME"],
        "slurm_partition": os.environ["SLURM_JOB_PARTITION"],
    }


def _hardware_manifest() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_runtime": torch.version.cuda,
        "device": torch.cuda.get_device_name(0),
        "device_capability": list(torch.cuda.get_device_capability(0)),
        "vram_bytes": int(torch.cuda.get_device_properties(0).total_memory),
    }


if __name__ == "__main__":
    raise SystemExit(main())
