"""CLI for the Klara 124M sparse-MoE pretraining lane."""

from __future__ import annotations

import argparse
import sys
from dataclasses import fields, replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import platform
from typing import Any, Sequence
import tomllib

import torch
from torch.utils.data import DataLoader

from klara.training.bpe_tokenizer import BPETokenizer
from klara.training.config import ModelConfig
from klara.training.data import read_corpus
from klara.training.moe import MoEConfig, SparseMoE, build_moe_model, routing_diagnostics
from klara.training.moe_pretrain import (
    MoEPretrainConfig,
    _build_optimizer,
    _build_scheduler,
    count_parameters,
    load_training_checkpoint,
    train_moe_pretrain,
)
from klara.training.shard_data import (
    PackedShardDataset,
    write_packed_shards,
)
from klara.training.trainer import model_state_sha256, seed_everything


def _read_toml(path: Path) -> dict[str, Any]:
    """Load a TOML config and preserve insertion-independent mapping types."""

    return tomllib.loads(path.read_text(encoding="utf-8"))


def _filter_for_dataclass(raw: dict[str, Any], cls: type) -> dict[str, Any]:
    """Return only keys accepted by a dataclass constructor."""

    allowed = {item.name for item in fields(cls)}
    return {key: value for key, value in raw.items() if key in allowed}


def _build_model(raw: dict[str, Any]) -> tuple[ModelConfig, MoEConfig, Any]:
    """Build the configured four-expert top-2 MoE model."""

    model_config = ModelConfig.from_dict(dict(raw["model"]))
    moe_config = MoEConfig(**dict(raw["moe"]))
    model = build_moe_model(model_config, moe_config)
    return model_config, moe_config, model


def _hardware_manifest() -> dict[str, Any]:
    """Record Python, PyTorch, CUDA, and bf16 capabilities."""

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
    """Require HKU Slurm lineage for formal cloud training."""

    if not bool(execution.get("require_slurm", False)):
        return
    required = {
        key: os.environ.get(key, "")
        for key in (
            "SLURM_JOB_ID",
            "SLURMD_NODENAME",
            "SLURM_JOB_PARTITION",
            "AGENTLADDER_SOURCE_DIR",
            "AGENTLADDER_SOURCE_BUNDLE_SHA256",
            "AGENTLADDER_PARENT_COMMIT",
        )
    }
    missing = sorted(key for key, value in required.items() if not value)
    if missing:
        raise RuntimeError(
            "formal MoE pretraining requires an HKU Slurm job and source lineage; "
            f"missing {missing}"
        )
    source = Path(required["AGENTLADDER_SOURCE_DIR"])
    remote_root = Path(
        str(execution.get("remote_root", "/userhome/cs2/u3665453/AgentLadder"))
    )
    try:
        source.relative_to(remote_root / "deployments")
    except ValueError as exc:
        raise RuntimeError("training source is outside HKU deployments") from exc
    if len(required["AGENTLADDER_SOURCE_BUNDLE_SHA256"]) != 64:
        raise RuntimeError("source bundle SHA-256 is malformed")
    if len(required["AGENTLADDER_PARENT_COMMIT"]) != 40:
        raise RuntimeError("parent commit is malformed")


def _make_smoke_config(raw: dict[str, Any]) -> MoEPretrainConfig:
    """Build a bounded smoke-training config from the ``[smoke]`` section."""

    smoke = dict(raw.get("smoke", {}))
    train_raw = {
        "seed": int(smoke.get("seed", 20260816)),
        "steps": int(smoke.get("steps", 30)),
        "batch_size": int(smoke.get("batch_size", 4)),
        "gradient_accumulation_steps": int(
            smoke.get("gradient_accumulation_steps", 2)
        ),
        "learning_rate": float(smoke.get("learning_rate", 0.003)),
        "weight_decay": float(smoke.get("weight_decay", 0.0)),
        "gradient_clip": float(smoke.get("gradient_clip", 1.0)),
        "precision": str(smoke.get("precision", "fp32")),
        "device": str(smoke.get("device", "cpu")),
        "warmup_steps": int(smoke.get("warmup_steps", 5)),
        "cosine_min_lr": float(smoke.get("cosine_min_lr", 0.0001)),
        "val_every": int(smoke.get("val_every", 10)),
        "log_every": int(smoke.get("log_every", 5)),
        "checkpoint_every": int(smoke.get("checkpoint_every", 10000)),
        "loader_workers": int(smoke.get("loader_workers", 0)),
    }
    return MoEPretrainConfig.from_dict(train_raw)


def _make_smoke_model_config(
    raw: dict[str, Any],
    *,
    vocab_size: int,
    sequence_length: int,
) -> ModelConfig:
    """Merge full model defaults with the small smoke architecture overrides."""

    smoke_model = dict(raw.get("smoke", {}).get("model", {}))
    merged = dict(raw["model"])
    merged.update(_filter_for_dataclass(smoke_model, ModelConfig))
    merged["vocab_size"] = vocab_size
    merged["max_sequence_length"] = sequence_length
    return ModelConfig.from_dict(merged)


def _ensure_val_shards(shard_dir: Path) -> Path:
    """Return a validation shard directory, falling back to train shards."""

    val_dir = Path(shard_dir) / "val"
    if any(val_dir.glob("shard_*.pt")):
        return val_dir
    train_dir = Path(shard_dir) / "train"
    if not any(train_dir.glob("shard_*.pt")):
        raise ValueError(f"no packed shards found under {shard_dir}")
    return train_dir


def _print_json(value: dict[str, Any]) -> None:
    """Print a JSON object with a trailing newline."""

    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------
def _parameter_breakdown(
    model: Any,
    moe_config: MoEConfig,
) -> dict[str, Any]:
    """Count total, trainable, expert, shared, and per-token active parameters."""

    total_parameters = count_parameters(model)
    trainable_parameters = sum(
        parameter.numel()
        for parameter in model.parameters()
        if parameter.requires_grad
    )
    expert_parameters = 0
    for module in model.modules():
        if isinstance(module, SparseMoE):
            expert_parameters += sum(
                parameter.numel() for parameter in module.experts.parameters()
            )
    shared_parameters = max(0, total_parameters - expert_parameters)
    if moe_config.num_experts > 0:
        active_expert_parameters = (
            expert_parameters * moe_config.top_k // moe_config.num_experts
        )
    else:  # pragma: no cover - MoEConfig always has four experts
        active_expert_parameters = 0
    approx_active_parameters_per_token = (
        shared_parameters + active_expert_parameters
    )
    return {
        "total_parameters": total_parameters,
        "trainable_parameters": trainable_parameters,
        "expert_parameters": expert_parameters,
        "shared_parameters": shared_parameters,
        "approx_active_parameters_per_token": approx_active_parameters_per_token,
    }


def run_params(config_path: Path) -> dict[str, Any]:
    """Instantiate the full model and report its exact parameter counts."""

    raw = _read_toml(config_path)
    model_config, moe_config, model = _build_model(raw)
    breakdown = _parameter_breakdown(model, moe_config)
    parameter_count = breakdown["total_parameters"]
    report = {
        "experiment": raw.get("experiment", {}).get(
            "name", "klara-moe-pretrain"
        ),
        "parameter_count": parameter_count,
        "parameter_count_readable": f"{parameter_count / 1e6:.6f}M",
        "target": "~124M",
        "model": model_config.to_dict(),
        "moe": {
            "num_experts": moe_config.num_experts,
            "top_k": moe_config.top_k,
            "auxiliary_loss_weight": moe_config.auxiliary_loss_weight,
            "z_loss_weight": moe_config.z_loss_weight,
        },
        **breakdown,
    }
    _print_json(report)
    print(f"parameter_count={parameter_count}", flush=True)
    return report


def _read_corpus_sample(path: Path, limit: int):
    """Yield up to ``limit`` non-empty stripped corpus lines without loading all."""
    with path.open("r", encoding="utf-8") as fh:
        for index, line in enumerate(fh):
            if index >= limit:
                break
            text = line.strip()
            if text:
                yield text


def run_preprocess(
    config_path: Path,
    corpus_path: Path,
    output_dir: Path,
    tokenizer_dir: Path,
) -> dict[str, Any]:
    """Train or load a BPE tokenizer and write packed train/val shards."""

    raw = _read_toml(config_path)
    model_config = ModelConfig.from_dict(dict(raw["model"]))
    target_vocab_size = int(raw.get("tokenizer", {}).get("target_vocab_size", 28000))
    sequence_length = model_config.max_sequence_length
    data_config = dict(raw.get("data", {}))
    shard_rows = int(data_config.get("shard_rows", 4096))
    val_ratio = float(data_config.get("val_ratio", 0.005))

    tokenizer_dir = Path(tokenizer_dir)
    vocab_path = tokenizer_dir / "vocab.json"
    merges_path = tokenizer_dir / "merges.txt"
    tokenizer_type = str(raw.get("tokenizer", {}).get("type", "bpe"))
    if tokenizer_type == "byte":
        from klara.training.tokenizer import ByteTokenizer

        tokenizer = ByteTokenizer()
        tokenizer_status = "byte"
    elif vocab_path.exists() and merges_path.exists():
        tokenizer = BPETokenizer.load(tokenizer_dir)
        tokenizer_status = "loaded"
    else:
        tokenizer = BPETokenizer()
        stats = tokenizer.train_from_texts(
            _read_corpus_sample(corpus_path, int(raw.get("tokenizer", {}).get("train_sample_lines", 1500000))),
            target_vocab_size=target_vocab_size,
        )
        tokenizer.save(tokenizer_dir)
        tokenizer_status = {
            "trained": True,
            "target_vocab_size": stats.target_vocab_size,
            "actual_vocab_size": stats.actual_vocab_size,
            "merge_count": stats.merge_count,
            "corpus_bytes": stats.corpus_bytes,
            "corpus_lines": stats.corpus_lines,
        }
    if tokenizer.vocab_size != model_config.vocab_size:
        raise ValueError(
            "tokenizer vocabulary does not match model config: "
            f"{tokenizer.vocab_size} != {model_config.vocab_size}"
        )

    manifest = write_packed_shards(
        corpus_path,
        tokenizer,
        output_dir,
        sequence_length=sequence_length,
        shard_rows=shard_rows,
        val_ratio=val_ratio,
        max_tokens=int(data_config.get("max_pack_tokens", 0)) or None,
    )
    report = {
        "schema_version": "klara.moe-pretrain.preprocess.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "corpus": corpus_path.as_posix(),
        "tokenizer_dir": tokenizer_dir.as_posix(),
        "tokenizer_vocab_size": tokenizer.vocab_size,
        "tokenizer_status": tokenizer_status,
        "packed_shards": manifest,
        "model_vocab_size": model_config.vocab_size,
    }
    _print_json(report)
    return report


def run_train(
    config_path: Path,
    shard_dir: Path,
    tokenizer_dir: Path,
    artifact_dir: Path,
    resume_from: Path | None,
) -> dict[str, Any]:
    """Run the full sparse-MoE pretraining loop."""

    raw = _read_toml(config_path)
    execution = dict(raw.get("execution", {}))
    _validate_execution_boundary(execution)
    if bool(execution.get("require_cuda_training", False)) and not torch.cuda.is_available():
        raise RuntimeError("formal MoE pretraining requires CUDA")

    model_config, moe_config, model = _build_model(raw)
    tokenizer_type = str(raw.get("tokenizer", {}).get("type", "bpe"))
    if tokenizer_type == "byte":
        from klara.training.tokenizer import ByteTokenizer

        tokenizer = ByteTokenizer()
    else:
        tokenizer = BPETokenizer.load(tokenizer_dir)
    if tokenizer.vocab_size != model_config.vocab_size:
        raise ValueError(
            "tokenizer vocabulary does not match model config: "
            f"{tokenizer.vocab_size} != {model_config.vocab_size}"
        )
    train_config = MoEPretrainConfig.from_dict(dict(raw["train"]))
    train_dir = Path(shard_dir) / "train"
    val_dir = _ensure_val_shards(shard_dir)
    train_dataset = PackedShardDataset(
        train_dir,
        batch_size=train_config.batch_size,
        sequence_length=model_config.max_sequence_length,
        seed=train_config.seed,
        shuffle=True,
        repeat=True,
        drop_last=True,
    )
    val_dataset = PackedShardDataset(
        val_dir,
        batch_size=train_config.batch_size,
        sequence_length=model_config.max_sequence_length,
        seed=train_config.seed,
        shuffle=False,
        repeat=False,
        drop_last=False,
    )
    parameter_count = count_parameters(model)
    print(f"parameter_count={parameter_count}", flush=True, file=sys.stderr)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result = train_moe_pretrain(
        model,
        moe_config,
        train_config,
        train_dataset=train_dataset,
        val_dataset=val_dataset,
        artifact_dir=artifact_dir,
        resume_from=resume_from,
    )
    report = {
        "schema_version": "klara.moe-pretrain.run.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "experiment": raw.get("experiment", {}).get(
            "name", "klara-moe-pretrain"
        ),
        "source": {
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
        "model": model_config.to_dict(),
        "moe": {
            "num_experts": moe_config.num_experts,
            "top_k": moe_config.top_k,
        },
        "train": train_config.to_dict(),
        "hardware": _hardware_manifest(),
        "parameter_count": parameter_count,
        "result": result.to_dict(),
    }
    (artifact_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (artifact_dir / "training_logs.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in result.logs)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _print_json(report)
    return report


def run_smoke(
    config_path: Path,
    corpus_path: Path,
    artifact_dir: Path,
) -> dict[str, Any]:
    """Run a local tiny-corpus smoke with checkpoint resume verification."""

    raw = _read_toml(config_path)
    smoke = dict(raw.get("smoke", {}))
    target_vocab_size = int(smoke.get("target_vocab_size", 512))
    sequence_length = int(smoke.get("sequence_length", 64))
    val_ratio = float(smoke.get("val_ratio", 0.2))
    shard_rows = int(smoke.get("shard_rows", 32))
    minimum_reduction = float(smoke.get("minimum_loss_reduction_fraction", 0.02))
    resume_extra_steps = int(smoke.get("resume_extra_steps", 5))

    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    texts = read_corpus(corpus_path)
    tokenizer = BPETokenizer()
    stats = tokenizer.train_from_texts(texts, target_vocab_size=target_vocab_size)
    tokenizer_dir = artifact_dir / "tokenizer"
    tokenizer.save(tokenizer_dir)

    model_config = _make_smoke_model_config(
        raw,
        vocab_size=tokenizer.vocab_size,
        sequence_length=sequence_length,
    )
    moe_config = MoEConfig(**dict(raw["moe"]))
    train_config = _make_smoke_config(raw)

    packed_manifest = write_packed_shards(
        corpus_path,
        tokenizer,
        artifact_dir / "shards",
        sequence_length=sequence_length,
        shard_rows=shard_rows,
        val_ratio=val_ratio,
    )

    def make_datasets():
        train_dataset = PackedShardDataset(
            artifact_dir / "shards" / "train",
            batch_size=train_config.batch_size,
            sequence_length=sequence_length,
            seed=train_config.seed,
            shuffle=True,
            repeat=True,
            drop_last=True,
        )
        val_dataset = PackedShardDataset(
            _ensure_val_shards(artifact_dir / "shards"),
            batch_size=train_config.batch_size,
            sequence_length=sequence_length,
            seed=train_config.seed,
            shuffle=False,
            repeat=False,
            drop_last=False,
        )
        return train_dataset, val_dataset

    phase1_steps = max(1, train_config.steps // 2)
    phase1_config = replace(
        train_config,
        steps=phase1_steps,
        checkpoint_every=phase1_steps,
    )
    seed_everything(phase1_config.seed)
    phase1_model = build_moe_model(model_config, moe_config)
    phase1_train, phase1_val = make_datasets()
    phase1_result = train_moe_pretrain(
        phase1_model,
        moe_config,
        phase1_config,
        train_dataset=phase1_train,
        val_dataset=phase1_val,
        artifact_dir=artifact_dir / "phase1",
    )
    phase1_checkpoint = artifact_dir / "phase1" / "checkpoint_final.pt"

    # Explicit save/load verification into a fresh model and optimizer.
    seed_everything(phase1_config.seed)
    reload_model = build_moe_model(model_config, moe_config)
    reload_optimizer = _build_optimizer(
        reload_model,
        phase1_config.learning_rate,
        phase1_config.weight_decay,
    )
    reload_scheduler = _build_scheduler(reload_optimizer, phase1_config)
    reload_details = load_training_checkpoint(
        phase1_checkpoint,
        model=reload_model,
        optimizer=reload_optimizer,
        scheduler=reload_scheduler,
        expected_sha256=phase1_result.final_checkpoint_sha256,
    )
    reload_exact = (
        model_state_sha256(reload_model) == phase1_result.model_state_sha256
    )

    # Resume from the same checkpoint and finish the remaining smoke steps.
    resume_steps = train_config.steps + resume_extra_steps
    resume_config = replace(
        train_config,
        steps=resume_steps,
        checkpoint_every=max(1, resume_steps),
    )
    seed_everything(resume_config.seed)
    resume_model = build_moe_model(model_config, moe_config)
    resume_train, resume_val = make_datasets()
    resume_result = train_moe_pretrain(
        resume_model,
        moe_config,
        resume_config,
        train_dataset=resume_train,
        val_dataset=resume_val,
        artifact_dir=artifact_dir / "resume",
        resume_from=phase1_checkpoint,
    )

    # Routing probe on all train rows after training.  Using the full train
    # shard (rather than a single validation row) gives a stable expert-load
    # estimate for the smoke gate and avoids small-sample collapse noise.
    diagnostic_model = resume_model.to("cpu").eval()
    diagnostic_train = PackedShardDataset(
        artifact_dir / "shards" / "train",
        batch_size=max(1, min(4, train_config.batch_size)),
        sequence_length=sequence_length,
        seed=train_config.seed,
        shuffle=False,
        repeat=False,
        drop_last=False,
    )
    diagnostic_inputs: list[torch.Tensor] = []
    for diagnostic_batch in DataLoader(
        diagnostic_train, batch_size=None, num_workers=0
    ):
        diagnostic_batch = diagnostic_batch.to(torch.device("cpu"))
        diagnostic_inputs.append(diagnostic_batch.input_ids)
    diagnostic_input = torch.cat(diagnostic_inputs, dim=0)
    diagnostics = routing_diagnostics(
        diagnostic_model,
        diagnostic_input,
        torch.ones_like(diagnostic_input, dtype=torch.bool),
        device=torch.device("cpu"),
    )

    overall_reduction = (
        (phase1_result.initial_val_loss - resume_result.final_val_loss)
        / phase1_result.initial_val_loss
        if phase1_result.initial_val_loss > 0
        else 0.0
    )
    expert_load = list(resume_result.final_expert_load)
    expert_load_not_collapsed = all(value > 0.0 for value in expert_load)
    checks = {
        "loss_reduction": overall_reduction >= minimum_reduction,
        "gradients_finite": phase1_result.gradients_finite
        and resume_result.gradients_finite,
        "expert_load_not_collapsed": expert_load_not_collapsed,
        "all_experts_used_after_training": bool(diagnostics["all_experts_used"]),
        "checkpoint_reload_exact": reload_exact,
        "resume_step_restored": reload_details["step"] == phase1_steps,
        "resume_completed": resume_result.final_step == resume_steps,
        "final_checkpoint_exists": (
            artifact_dir / "resume" / "checkpoint_final.pt"
        ).exists(),
    }
    report = {
        "schema_version": "klara.moe-pretrain.smoke.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "corpus": corpus_path.as_posix(),
        "tokenizer_vocab_size": tokenizer.vocab_size,
        "tokenizer_merges": len(tokenizer.merges),
        "tokenizer_training": {
            "target_vocab_size": stats.target_vocab_size,
            "actual_vocab_size": stats.actual_vocab_size,
            "corpus_bytes": stats.corpus_bytes,
            "corpus_lines": stats.corpus_lines,
        },
        "packed_shards": packed_manifest,
        "model": model_config.to_dict(),
        "moe": {
            "num_experts": moe_config.num_experts,
            "top_k": moe_config.top_k,
        },
        "phase1_steps": phase1_steps,
        "resume_steps": resume_steps,
        "phase1": phase1_result.to_dict(),
        "resume": resume_result.to_dict(),
        "overall_loss_reduction_fraction": overall_reduction,
        "routing_diagnostics": diagnostics,
        "checks": checks,
        "passed": all(checks.values()),
    }
    (artifact_dir / "smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _print_json(report)
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the MoE pretraining command surface."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    params = subparsers.add_parser("params", help="print full model parameter count")
    params.add_argument("--config", type=Path, required=True)

    preprocess = subparsers.add_parser(
        "preprocess", help="train BPE and write packed shards"
    )
    preprocess.add_argument("--config", type=Path, required=True)
    preprocess.add_argument("--corpus", type=Path, required=True)
    preprocess.add_argument("--output-dir", type=Path, required=True)
    preprocess.add_argument("--tokenizer-dir", type=Path, required=True)

    train = subparsers.add_parser("train", help="run full MoE pretraining")
    train.add_argument("--config", type=Path, required=True)
    train.add_argument("--shard-dir", type=Path, required=True)
    train.add_argument("--tokenizer-dir", type=Path, required=True)
    train.add_argument("--artifact-dir", type=Path, required=True)
    train.add_argument("--resume-from", type=Path, default=None)

    smoke = subparsers.add_parser("smoke", help="run local tiny-corpus smoke")
    smoke.add_argument("--config", type=Path, required=True)
    smoke.add_argument("--corpus", type=Path, required=True)
    smoke.add_argument("--artifact-dir", type=Path, required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return nonzero on failure."""

    args = build_parser().parse_args(argv)
    if args.command == "params":
        run_params(args.config)
    elif args.command == "preprocess":
        run_preprocess(args.config, args.corpus, args.output_dir, args.tokenizer_dir)
    elif args.command == "train":
        run_train(
            args.config,
            args.shard_dir,
            args.tokenizer_dir,
            args.artifact_dir,
            args.resume_from,
        )
    elif args.command == "smoke":
        report = run_smoke(args.config, args.corpus, args.artifact_dir)
        return 0 if report["passed"] else 1
    else:  # pragma: no cover - argparse owns choices
        raise ValueError(f"unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
