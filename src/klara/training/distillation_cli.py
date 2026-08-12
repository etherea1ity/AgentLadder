"""HKU-only entry point for multi-teacher public-trajectory distillation."""

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

from klara.eval.cli import run_gate
from klara.eval.trajectory import canonical_json, stable_sha256
from klara.training.checkpoint import load_checkpoint, save_checkpoint
from klara.training.config import ModelConfig
from klara.training.distillation import (
    DISTILLATION_SCORER_VERSION,
    FrozenTeacherManifest,
    train_hard_label_sft,
)
from klara.training.distillation_report import DistillationReport
from klara.training.model import TinyDecoderLM
from klara.training.tokenizer import ByteTokenizer
from klara.training.trainer import model_state_sha256, seed_everything


def run_distillation(config_path: Path, artifact_dir: Path) -> DistillationReport:
    """Load the frozen student, SFT public labels, and enforce Gate 3."""

    raw_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    experiment = dict(raw_config["experiment"])
    execution = dict(raw_config["execution"])
    student_config = dict(raw_config["student"])
    manifest_config = dict(raw_config["manifest"])
    train_config = dict(raw_config["train"])
    gate_config = dict(raw_config["gate"])
    _validate_execution_boundary(execution)
    if bool(execution.get("require_cuda_training")) and not torch.cuda.is_available():
        raise RuntimeError("formal distillation requires CUDA")
    source_dir = Path(os.environ["AGENTLADDER_SOURCE_DIR"])
    manifest_path = source_dir / str(manifest_config["path"])
    manifest = FrozenTeacherManifest.load(
        manifest_path,
        expected_sha256=str(manifest_config["sha256"]),
    )
    model_config = ModelConfig.from_dict(dict(raw_config["model"]))
    tokenizer = ByteTokenizer()
    seed = int(train_config["seed"])
    seed_everything(seed)
    model = TinyDecoderLM(model_config)
    base_checkpoint = Path(str(student_config["base_checkpoint"]))
    base_sha256 = str(student_config["base_checkpoint_sha256"])
    base_details = load_checkpoint(
        base_checkpoint,
        model=model,
        expected_sha256=base_sha256,
    )
    result = train_hard_label_sft(
        model,
        manifest,
        tokenizer,
        steps=int(train_config["steps"]),
        batch_size=int(train_config["batch_size"]),
        learning_rate=float(train_config["learning_rate"]),
        weight_decay=float(train_config["weight_decay"]),
        gradient_clip=float(train_config["gradient_clip"]),
        seed=seed,
        device_name=str(train_config["device"]),
    )

    baseline_path = source_dir / str(gate_config["evidence_baseline_report"])
    expected_baseline_sha256 = str(gate_config["evidence_baseline_sha256"])
    if _file_sha256(baseline_path) != expected_baseline_sha256:
        raise ValueError("frozen evidence baseline SHA-256 mismatch")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current_evidence = run_gate(
        source_dir / "tests/fixtures/algorithm/gate1_gold.json",
        source_dir / "config/experiments/lab_a_evidence_eval.toml",
    )
    baseline_metrics = dict(baseline["metrics"])
    current_metrics = dict(current_evidence.metrics)
    not_regressed = all(
        float(current_metrics[key]) >= float(value)
        for key, value in baseline_metrics.items()
    )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    hardware = _hardware_manifest()
    config_sha256 = stable_sha256(canonical_json(raw_config))
    scorer_sha256 = stable_sha256(DISTILLATION_SCORER_VERSION)
    checkpoint_path = artifact_dir / "tiny_distilled.pt"
    checkpoint_sha256 = save_checkpoint(
        checkpoint_path,
        model=model,
        optimizer=None,
        step=int(train_config["steps"]),
        metadata={
            "base_checkpoint_sha256": base_sha256,
            "manifest_sha256": manifest.sha256,
            "config_sha256": config_sha256,
            "scorer_version": DISTILLATION_SCORER_VERSION,
            "scorer_sha256": scorer_sha256,
            "seed": seed,
            "supervision": "hard_label_sft",
            "api_teacher_kl_weight": 0.0,
            "hardware": hardware,
        },
    )
    restored = TinyDecoderLM(model_config)
    checkpoint_details = load_checkpoint(
        checkpoint_path,
        model=restored,
        expected_sha256=checkpoint_sha256,
    )
    restored_model_sha256 = model_state_sha256(restored)
    dataset = manifest.dataset_summary()
    training = result.to_dict()
    evidence_control = {
        "baseline_sha256": expected_baseline_sha256,
        "baseline_metrics": baseline_metrics,
        "current_metrics": current_metrics,
        "current_passed": current_evidence.passed,
        "not_regressed": not_regressed,
    }
    minimum_gain = float(gate_config["minimum_accuracy_gain"])
    checks = {
        "single_frozen_manifest": manifest.sha256 == str(manifest_config["sha256"]),
        "qwen_and_deepseek_present": set(dataset["teacher_counts"]) == {"qwen", "deepseek"},
        "public_schema_validated": dataset["schema_validation_rate"] == 1.0,
        "redaction_complete": dataset["redaction_pass_rate"] == 1.0,
        "deduplication_complete": dataset["deduplication_pass_rate"] == 1.0,
        "split_hashes_disjoint": bool(dataset["split_hashes_disjoint"]),
        "api_teacher_hard_labels_only": all(
            teacher["supervision"] == "hard_label_sft"
            and float(teacher["kl_weight"]) == 0.0
            for teacher in manifest.teachers
        ),
        "heldout_accuracy_improved": (
            result.post_sft_accuracy - result.pre_sft_accuracy >= minimum_gain
        ),
        "validation_accuracy": result.validation_accuracy
        >= float(gate_config["minimum_validation_accuracy"]),
        "post_sft_test_accuracy": result.post_sft_accuracy
        >= float(gate_config["minimum_post_sft_test_accuracy"]),
        "evidence_control_not_regressed": current_evidence.passed and not_regressed,
        "finite_gradients": result.gradients_finite,
        "gpu_peak_under_limit": result.peak_allocated_bytes
        < int(gate_config["maximum_gpu_peak_allocated_bytes"]),
        "base_checkpoint_hash_verified": base_details["sha256"] == base_sha256,
        "checkpoint_hash_verified": checkpoint_details["sha256"] == checkpoint_sha256,
        "checkpoint_reload_exact": restored_model_sha256 == result.model_state_sha256,
        "slurm_cuda_execution": bool(os.environ.get("SLURM_JOB_ID"))
        and str(train_config["device"]) == "cuda",
    }
    report = DistillationReport(
        experiment=str(experiment["name"]),
        evaluated_at=datetime.now(UTC).isoformat(),
        source=_source_manifest(),
        dataset=dataset,
        student={
            "base_checkpoint": base_checkpoint.as_posix(),
            "base_checkpoint_sha256": base_sha256,
            "base_checkpoint_step": base_details["step"],
            "architecture": model_config.to_dict(),
        },
        training=training,
        evidence_control=evidence_control,
        checkpoint={
            "path": checkpoint_path.as_posix(),
            "sha256": checkpoint_sha256,
            "step": checkpoint_details["step"],
            "model_state_sha256": result.model_state_sha256,
            "restored_model_state_sha256": restored_model_sha256,
        },
        hashes={
            "config_sha256": config_sha256,
            "manifest_sha256": manifest.sha256,
            "scorer_sha256": scorer_sha256,
            "evidence_baseline_sha256": expected_baseline_sha256,
        },
        hardware=hardware,
        checks=checks,
        passed=all(checks.values()),
    )
    (artifact_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "klara.distillation-run.v1",
                **report.to_dict(),
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
    """Build the bounded Gate 3 command."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute Gate 3 and return nonzero when any hard gate fails."""

    args = build_parser().parse_args(argv)
    report = run_distillation(args.config, args.artifact_dir)
    args.json_out.write_text(report.to_json(), encoding="utf-8", newline="\n")
    args.markdown_out.write_text(report.to_markdown(), encoding="utf-8", newline="\n")
    print(report.to_json(), end="")
    return 0 if report.passed else 1


def _validate_execution_boundary(execution: dict[str, Any]) -> None:
    """Refuse formal distillation without an HKU Slurm source lineage."""

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
    if bool(execution.get("require_slurm")) and any(not value for value in required.values()):
        raise RuntimeError("formal distillation requires HKU Slurm source lineage")
    source = Path(required["AGENTLADDER_SOURCE_DIR"])
    expected = Path(str(execution["remote_root"])) / "deployments"
    try:
        source.relative_to(expected)
    except ValueError as exc:
        raise RuntimeError("distillation source is outside HKU deployments") from exc
    if len(required["AGENTLADDER_SOURCE_BUNDLE_SHA256"]) != 64:
        raise RuntimeError("source bundle SHA-256 is malformed")
    if len(required["AGENTLADDER_PARENT_COMMIT"]) != 40:
        raise RuntimeError("parent commit is malformed")


def _source_manifest() -> dict[str, str]:
    """Return exact Slurm and source lineage."""

    return {
        "parent_commit": os.environ["AGENTLADDER_PARENT_COMMIT"],
        "bundle_sha256": os.environ["AGENTLADDER_SOURCE_BUNDLE_SHA256"],
        "deployment": os.environ["AGENTLADDER_SOURCE_DIR"],
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "slurm_node": os.environ["SLURMD_NODENAME"],
        "slurm_partition": os.environ["SLURM_JOB_PARTITION"],
    }


def _hardware_manifest() -> dict[str, Any]:
    """Record the exact cloud runtime."""

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


def _file_sha256(path: Path) -> str:
    """Hash one frozen input file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
