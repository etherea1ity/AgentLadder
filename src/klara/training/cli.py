"""CLI for repository-native tiny pretraining experiments."""

from __future__ import annotations

import argparse
from dataclasses import asdict
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
from klara.training.pretrain_report import PretrainReport
from klara.training.tokenizer import ByteTokenizer
from klara.training.trainer import (
    PRETRAIN_SCORER_VERSION,
    cpu_reproducibility_hash,
    gpu_memory_smoke,
    model_state_sha256,
    seed_everything,
    train_language_model,
)


def run_pretrain(
    config_path: Path,
    corpus_path: Path,
    artifact_dir: Path,
) -> PretrainReport:
    """Execute training, checkpoint reload, CPU replay, and GPU memory gates."""

    raw_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    model_config = ModelConfig.from_dict(dict(raw_config.get("model", {})))
    train_config = TrainConfig.from_dict(dict(raw_config.get("train", {})))
    experiment = dict(raw_config.get("experiment", {}))
    execution = dict(raw_config.get("execution", {}))
    generation = dict(raw_config.get("generation", {}))
    gate = dict(raw_config.get("gate", {}))
    _validate_execution_boundary(execution)
    if bool(execution.get("require_cuda_training", False)):
        if train_config.device == "cpu":
            raise RuntimeError("formal cloud training cannot request the CPU device")
        if not torch.cuda.is_available():
            raise RuntimeError(
                "formal cloud training requires CUDA and will not fall back to CPU"
            )
    tokenizer = ByteTokenizer()
    if tokenizer.vocab_size != model_config.vocab_size:
        raise ValueError("byte tokenizer vocabulary does not match model config")
    texts = read_corpus(corpus_path)
    batches = build_causal_batches(
        texts,
        tokenizer,
        sequence_length=model_config.max_sequence_length,
        batch_size=train_config.batch_size,
    )

    gpu_smoke = gpu_memory_smoke(model_config, seed=train_config.seed)
    prompt = str(generation.get("prompt", "Klara "))
    first_cpu_hash = cpu_reproducibility_hash(
        model_config,
        tokenizer=tokenizer,
        prompt=prompt,
        seed=train_config.seed,
    )
    second_cpu_hash = cpu_reproducibility_hash(
        model_config,
        tokenizer=tokenizer,
        prompt=prompt,
        seed=train_config.seed,
    )

    seed_everything(train_config.seed)
    model = TinyDecoderLM(model_config)
    training_result, _optimizer = train_language_model(
        model,
        batches,
        train_config,
        tokenizer=tokenizer,
        generation_prompt=prompt,
    )
    hardware = _hardware_manifest()
    config_hash = stable_sha256(canonical_json(raw_config))
    data_hash = _file_sha256(corpus_path)
    scorer_hash = stable_sha256(PRETRAIN_SCORER_VERSION)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = artifact_dir / "tiny_dense.pt"
    checkpoint_hash = save_checkpoint(
        checkpoint_path,
        model=model,
        optimizer=None,
        step=train_config.steps,
        metadata={
            "config_sha256": config_hash,
            "data_sha256": data_hash,
            "seed": train_config.seed,
            "precision": train_config.precision,
            "hardware": hardware,
            "scorer_version": PRETRAIN_SCORER_VERSION,
            "scorer_sha256": scorer_hash,
        },
    )
    seed_everything(train_config.seed + 1)
    restored = TinyDecoderLM(model_config)
    checkpoint_details = load_checkpoint(
        checkpoint_path,
        model=restored,
        expected_sha256=checkpoint_hash,
    )
    restored_hash = model_state_sha256(restored)
    reload_exact = restored_hash == training_result.model_state_sha256
    comparison_batch = batches[0]
    model.to("cpu").eval()
    restored.eval()
    with torch.inference_mode():
        original_logits = model(
            comparison_batch.input_ids,
            attention_mask=comparison_batch.attention_mask,
        ).logits
        restored_logits = restored(
            comparison_batch.input_ids,
            attention_mask=comparison_batch.attention_mask,
        ).logits
    checkpoint_logit_max_abs_diff = float(
        (original_logits - restored_logits).abs().max().item()
    )
    checkpoint_logit_atol = float(gate["checkpoint_logit_atol"])

    minimum_reduction = float(gate["minimum_loss_reduction_fraction"])
    maximum_peak = int(gate["maximum_gpu_peak_allocated_bytes"])
    checks = {
        "loss_reduction": training_result.loss_reduction_fraction
        >= minimum_reduction,
        "finite_gradients": training_result.gradients_finite,
        "cpu_same_seed_reproducible": first_cpu_hash == second_cpu_hash,
        "gpu_smoke_available": bool(gpu_smoke["available"]),
        "gpu_smoke_finite_and_under_limit": bool(gpu_smoke["passed"])
        and int(gpu_smoke["peak_allocated_bytes"]) < maximum_peak,
        "training_peak_under_limit": training_result.peak_allocated_bytes
        < maximum_peak,
        "checkpoint_hash_verified": checkpoint_details["sha256"]
        == checkpoint_hash,
        "checkpoint_reload_exact": reload_exact,
        "checkpoint_logits_within_tolerance": checkpoint_logit_max_abs_diff
        <= checkpoint_logit_atol,
        "slurm_execution": bool(os.environ.get("SLURM_JOB_ID")),
        "cuda_training": (
            training_result.device.startswith("cuda")
            if bool(execution.get("require_cuda_training", False))
            else True
        ),
    }
    report = PretrainReport(
        experiment=str(experiment.get("name", "tiny-pretrain")),
        evaluated_at=datetime.now(UTC).isoformat(),
        source={
            "parent_commit": os.environ.get("AGENTLADDER_PARENT_COMMIT", "unknown"),
            "bundle_sha256": os.environ.get(
                "AGENTLADDER_SOURCE_BUNDLE_SHA256",
                "unknown",
            ),
            "deployment": os.environ.get("AGENTLADDER_SOURCE_DIR", "unknown"),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID", "not-slurm"),
            "slurm_node": os.environ.get("SLURMD_NODENAME", "not-slurm"),
            "slurm_partition": os.environ.get(
                "SLURM_JOB_PARTITION",
                "not-slurm",
            ),
        },
        model=model_config.to_dict(),
        train=train_config.to_dict(),
        hashes={
            "config_sha256": config_hash,
            "data_sha256": data_hash,
            "model_state_sha256": training_result.model_state_sha256,
            "restored_model_state_sha256": restored_hash,
            "scorer_sha256": scorer_hash,
        },
        hardware=hardware,
        result=training_result.to_dict(),
        cpu_reproducibility={
            "first_sha256": first_cpu_hash,
            "second_sha256": second_cpu_hash,
            "matched": first_cpu_hash == second_cpu_hash,
        },
        gpu_smoke=gpu_smoke,
        checkpoint={
            "format": "klara.tiny-lm.checkpoint.v1",
            "path": checkpoint_path.as_posix(),
            "sha256": checkpoint_hash,
            "step": checkpoint_details["step"],
            "reload_model_state_sha256": restored_hash,
            "logit_max_abs_diff": checkpoint_logit_max_abs_diff,
            "logit_atol": checkpoint_logit_atol,
        },
        checks=checks,
        passed=all(checks.values()),
    )
    manifest_path = artifact_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "klara.training-run.v1",
                "experiment": report.experiment,
                "evaluated_at": report.evaluated_at,
                "source": report.source,
                "checkpoint": report.checkpoint,
                "hashes": report.hashes,
                "model": report.model,
                "train": report.train,
                "hardware": report.hardware,
                "checks": report.checks,
                "passed": report.passed,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the bounded pretraining command surface."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    pretrain = subparsers.add_parser("pretrain", help="run tiny dense pretraining")
    pretrain.add_argument("--config", type=Path, required=True)
    pretrain.add_argument("--corpus", type=Path, required=True)
    pretrain.add_argument("--artifact-dir", type=Path, required=True)
    pretrain.add_argument("--json-out", type=Path, required=True)
    pretrain.add_argument("--markdown-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one experiment and return nonzero when a hard gate fails."""

    args = build_parser().parse_args(argv)
    if args.command != "pretrain":  # pragma: no cover - argparse owns choices
        raise ValueError(f"unknown command: {args.command}")
    report = run_pretrain(args.config, args.corpus, args.artifact_dir)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(report.to_json(), encoding="utf-8", newline="\n")
    args.markdown_out.write_text(
        report.to_markdown(),
        encoding="utf-8",
        newline="\n",
    )
    print(report.to_json(), end="")
    return 0 if report.passed else 1


def _hardware_manifest() -> dict[str, Any]:
    """Record exact Python, PyTorch, CUDA, and accelerator capabilities."""

    cuda_available = torch.cuda.is_available()
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda_available": cuda_available,
        "cuda_runtime": torch.version.cuda,
        "device": torch.cuda.get_device_name(0) if cuda_available else "cpu",
        "device_capability": (
            list(torch.cuda.get_device_capability(0)) if cuda_available else None
        ),
        "vram_bytes": (
            int(torch.cuda.get_device_properties(0).total_memory)
            if cuda_available
            else 0
        ),
        "bf16_supported": (
            bool(torch.cuda.is_bf16_supported()) if cuda_available else False
        ),
    }


def _validate_execution_boundary(execution: dict[str, Any]) -> None:
    """Refuse a formal cloud run without traceable Slurm source lineage."""

    if not bool(execution.get("require_slurm", False)):
        return
    required_environment = {
        "SLURM_JOB_ID": os.environ.get("SLURM_JOB_ID", ""),
        "SLURMD_NODENAME": os.environ.get("SLURMD_NODENAME", ""),
        "SLURM_JOB_PARTITION": os.environ.get("SLURM_JOB_PARTITION", ""),
        "AGENTLADDER_SOURCE_DIR": os.environ.get("AGENTLADDER_SOURCE_DIR", ""),
        "AGENTLADDER_SOURCE_BUNDLE_SHA256": os.environ.get(
            "AGENTLADDER_SOURCE_BUNDLE_SHA256",
            "",
        ),
        "AGENTLADDER_PARENT_COMMIT": os.environ.get(
            "AGENTLADDER_PARENT_COMMIT",
            "",
        ),
    }
    missing = sorted(key for key, value in required_environment.items() if not value)
    if missing:
        raise RuntimeError(
            "formal pretraining requires an HKU Slurm job and source lineage; "
            f"missing {missing}"
        )
    source_dir = Path(required_environment["AGENTLADDER_SOURCE_DIR"])
    remote_root = Path(
        str(execution.get("remote_root", "/userhome/cs2/u3665453/AgentLadder"))
    )
    expected_deployments = remote_root / "deployments"
    try:
        source_dir.relative_to(expected_deployments)
    except ValueError as exc:
        raise RuntimeError(
            "formal pretraining source must be inside the configured HKU "
            "deployments directory"
        ) from exc
    bundle_hash = required_environment["AGENTLADDER_SOURCE_BUNDLE_SHA256"]
    parent_commit = required_environment["AGENTLADDER_PARENT_COMMIT"]
    if len(bundle_hash) != 64 or any(character not in "0123456789abcdef" for character in bundle_hash):
        raise RuntimeError("source bundle SHA-256 is malformed")
    if len(parent_commit) != 40 or any(character not in "0123456789abcdef" for character in parent_commit):
        raise RuntimeError("parent commit is malformed")


def _file_sha256(path: Path) -> str:
    """Hash one small experiment input file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
