"""CLI for Klara MoE SFT and GRPO training lanes."""

from __future__ import annotations

import argparse
from dataclasses import fields
from datetime import UTC, datetime
import json
from pathlib import Path
import platform
import sys
from typing import Any, Sequence
import tomllib

import torch

from klara.training.bpe_tokenizer import BPETokenizer
from klara.training.config import ModelConfig
from klara.training.grpo import (
    GRPOConfig,
    build_rollout_prompt_text,
    load_tasks,
    train_grpo,
)
from klara.training.moe import MoEConfig, build_moe_model
from klara.training.sft import (
    SFTConfig,
    load_trajectories,
    render_trajectory,
    train_sft,
)


def _read_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _filter_for_dataclass(raw: dict[str, Any], cls: type) -> dict[str, Any]:
    allowed = {item.name for item in fields(cls)}
    return {key: value for key, value in raw.items() if key in allowed}


def _build_model(raw: dict[str, Any]) -> tuple[ModelConfig, MoEConfig, Any]:
    model_config = ModelConfig.from_dict(dict(raw["model"]))
    moe_config = MoEConfig(**dict(raw["moe"]))
    model = build_moe_model(model_config, moe_config)
    return model_config, moe_config, model


def _hardware_manifest() -> dict[str, Any]:
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


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _load_tokenizer(
    raw: dict[str, Any],
    model_config: ModelConfig,
    *,
    trajectories_path: Path,
    tokenizer_dir: Path,
    mode: str,
) -> tuple[BPETokenizer, Any]:
    tokenizer_dir = Path(tokenizer_dir)
    tokenizer_type = str(raw.get("tokenizer", {}).get("type", "bpe"))
    if tokenizer_type == "byte":
        from klara.training.tokenizer import ByteTokenizer

        tokenizer = ByteTokenizer()
        if tokenizer.vocab_size != model_config.vocab_size:
            raise ValueError(
                "tokenizer vocabulary does not match model config: "
                f"{tokenizer.vocab_size} != {model_config.vocab_size}"
            )
        return tokenizer, "byte"
    vocab_path = tokenizer_dir / "vocab.json"
    merges_path = tokenizer_dir / "merges.txt"
    if vocab_path.exists() and merges_path.exists():
        tokenizer = BPETokenizer.load(tokenizer_dir)
        tokenizer_status = "loaded"
    else:
        target_vocab_size = int(
            raw.get("tokenizer", {}).get("target_vocab_size", model_config.vocab_size)
        )
        records = load_trajectories(trajectories_path)
        if mode == "sft":
            texts = [render_trajectory(record) for record in records]
        elif mode == "grpo":
            tasks = load_tasks(trajectories_path)
            texts = [build_rollout_prompt_text(task) for task in tasks]
        else:
            raise ValueError(f"unknown tokenizer training mode: {mode!r}")
        tokenizer = BPETokenizer()
        stats = tokenizer.train_from_texts(
            texts,
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
    return tokenizer, tokenizer_status


def _resolve_trajectories(raw: dict[str, Any], explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    data = raw.get("data", {})
    if data.get("trajectories_path"):
        return Path(str(data["trajectories_path"]))
    return Path("data/trajectories/clean.jsonl")


def run_sft(
    config_path: Path,
    trajectories_path: Path,
    tokenizer_dir: Path,
    artifact_dir: Path,
    resume_from: Path | None,
    pretrain_from: Path | None,
) -> dict[str, Any]:
    raw = _read_toml(config_path)
    model_config, moe_config, model = _build_model(raw)
    train_config = SFTConfig.from_dict(_filter_for_dataclass(dict(raw["train"]), SFTConfig))
    tokenizer, tokenizer_status = _load_tokenizer(
        raw,
        model_config,
        trajectories_path=trajectories_path,
        tokenizer_dir=tokenizer_dir,
        mode="sft",
    )
    records = load_trajectories(trajectories_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    print(f"parameter_count={parameter_count}", flush=True, file=sys.stderr)
    result = train_sft(
        model,
        moe_config,
        train_config,
        records=records,
        tokenizer=tokenizer,
        artifact_dir=artifact_dir,
        resume_from=resume_from,
        pretrain_from=pretrain_from,
    )
    report = {
        "schema_version": "klara.moe-sft.run.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "experiment": raw.get("experiment", {}).get("name", "klara-moe-sft"),
        "trajectories": trajectories_path.as_posix(),
        "tokenizer_dir": tokenizer_dir.as_posix(),
        "tokenizer_status": tokenizer_status,
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


def run_grpo(
    config_path: Path,
    trajectories_path: Path,
    tokenizer_dir: Path,
    artifact_dir: Path,
    resume_from: Path | None,
    pretrain_from: Path | None,
) -> dict[str, Any]:
    raw = _read_toml(config_path)
    model_config, moe_config, model = _build_model(raw)
    train_config = GRPOConfig.from_dict(_filter_for_dataclass(dict(raw["train"]), GRPOConfig))
    tokenizer, tokenizer_status = _load_tokenizer(
        raw,
        model_config,
        trajectories_path=trajectories_path,
        tokenizer_dir=tokenizer_dir,
        mode="grpo",
    )
    tasks = load_tasks(trajectories_path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    print(f"parameter_count={parameter_count}", flush=True, file=sys.stderr)
    result = train_grpo(
        model,
        moe_config,
        train_config,
        tasks=tasks,
        tokenizer=tokenizer,
        artifact_dir=artifact_dir,
        resume_from=resume_from,
        pretrain_from=pretrain_from,
    )
    report = {
        "schema_version": "klara.moe-grpo.run.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "experiment": raw.get("experiment", {}).get("name", "klara-moe-grpo"),
        "trajectories": trajectories_path.as_posix(),
        "tokenizer_dir": tokenizer_dir.as_posix(),
        "tokenizer_status": tokenizer_status,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sft = subparsers.add_parser("sft", help="run trajectory SFT")
    sft.add_argument("--config", type=Path, required=True)
    sft.add_argument("--trajectories", type=Path, default=None)
    sft.add_argument("--tokenizer-dir", type=Path, required=True)
    sft.add_argument("--artifact-dir", type=Path, required=True)
    sft.add_argument("--resume-from", type=Path, default=None)
    sft.add_argument("--pretrain-from", type=Path, default=None)

    grpo = subparsers.add_parser("grpo", help="run GRPO training")
    grpo.add_argument("--config", type=Path, required=True)
    grpo.add_argument("--trajectories", type=Path, default=None)
    grpo.add_argument("--tokenizer-dir", type=Path, required=True)
    grpo.add_argument("--artifact-dir", type=Path, required=True)
    grpo.add_argument("--resume-from", type=Path, default=None)
    grpo.add_argument("--pretrain-from", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sft":
        raw = _read_toml(args.config)
        trajectories = _resolve_trajectories(raw, args.trajectories)
        run_sft(
            args.config,
            trajectories,
            args.tokenizer_dir,
            args.artifact_dir,
            args.resume_from,
            args.pretrain_from,
        )
    elif args.command == "grpo":
        raw = _read_toml(args.config)
        trajectories = _resolve_trajectories(raw, args.trajectories)
        run_grpo(
            args.config,
            trajectories,
            args.tokenizer_dir,
            args.artifact_dir,
            args.resume_from,
            args.pretrain_from,
        )
    else:  # pragma: no cover - argparse owns choices
        raise ValueError(f"unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
