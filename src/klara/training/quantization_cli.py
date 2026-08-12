"""HKU-only real FP16 AMP and packed FP4/W4A16 acceptance gate."""

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
from klara.training.distillation import (
    FrozenTeacherManifest,
    build_sft_batches,
    tool_decision_accuracy,
)
from klara.training.model import TinyDecoderLM
from klara.training.quantization import (
    FP4_FORMAT_VERSION,
    W4A16Linear,
    e2m1_decode,
    e2m1_encode,
    fake_quantize_gated_linears,
    materialize_fake_quant_model,
    pack_nibbles,
    quantize_gated_linears,
    unpack_nibbles,
)
from klara.training.quantization_report import QuantizationReport
from klara.training.tokenizer import ByteTokenizer
from klara.training.trainer import seed_everything, train_language_model


QUANTIZATION_SCORER_VERSION = "klara.fp16-fp4-eval.v1"


def run_quantization(
    config_path: Path,
    corpus_path: Path,
    artifact_dir: Path,
) -> QuantizationReport:
    """Train FP16 AMP, pack FP4, evaluate held-out quality, and optionally QAT."""

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    execution = dict(raw["execution"])
    _validate_execution_boundary(execution)
    if bool(execution["require_cuda_training"]) and not torch.cuda.is_available():
        raise RuntimeError("formal quantization gate requires CUDA")
    model_config = ModelConfig.from_dict(dict(raw["model"]))
    fp16_config = TrainConfig.from_dict(dict(raw["fp16_train"]))
    fp4_config = dict(raw["fp4"])
    qat_config = dict(raw["qat"])
    gate = dict(raw["gate"])
    student = dict(raw["student"])
    manifest_config = dict(raw["teacher_manifest"])
    tokenizer = ByteTokenizer()
    texts = read_corpus(corpus_path)
    batches = build_causal_batches(
        texts,
        tokenizer,
        sequence_length=model_config.max_sequence_length,
        batch_size=fp16_config.batch_size,
    )
    seed_everything(fp16_config.seed)
    amp_model = TinyDecoderLM(model_config)
    fp16_training, _ = train_language_model(
        amp_model,
        batches,
        fp16_config,
        tokenizer=tokenizer,
        generation_prompt="Klara ",
    )
    comparison = batches[0].to(torch.device("cuda"))
    amp_model.eval()
    with torch.inference_mode():
        fp32_logits = amp_model(
            comparison.input_ids,
            attention_mask=comparison.attention_mask,
        ).logits
        with torch.autocast("cuda", dtype=torch.float16):
            fp16_logits = amp_model(
                comparison.input_ids,
                attention_mask=comparison.attention_mask,
            ).logits
    logit_diff = float((fp32_logits - fp16_logits).abs().max().item())
    artifact_dir.mkdir(parents=True, exist_ok=True)
    amp_path = artifact_dir / "tiny_fp16_amp.pt"
    amp_sha256 = save_checkpoint(
        amp_path,
        model=amp_model,
        optimizer=None,
        step=fp16_config.steps,
        metadata={"precision": "fp16_amp", "scorer": QUANTIZATION_SCORER_VERSION},
    )

    base_path = Path(str(student["base_checkpoint"]))
    base_sha256 = str(student["base_checkpoint_sha256"])
    seed_everything(fp16_config.seed)
    base_model = TinyDecoderLM(model_config)
    base_details = load_checkpoint(
        base_path,
        model=base_model,
        expected_sha256=base_sha256,
    )
    source_dir = Path(os.environ["AGENTLADDER_SOURCE_DIR"])
    manifest_path = source_dir / str(manifest_config["path"])
    manifest = FrozenTeacherManifest.load(
        manifest_path,
        expected_sha256=str(manifest_config["sha256"]),
    )
    test_examples = manifest.split("test")
    device = torch.device("cuda")
    fp32_accuracy = tool_decision_accuracy(
        base_model,
        test_examples,
        tokenizer,
        device=device,
        precision="fp32",
    )
    block_size = int(fp4_config["block_size"])
    w4a16_model, storage = quantize_gated_linears(
        base_model,
        block_size=block_size,
    )
    w4a16_accuracy = tool_decision_accuracy(
        w4a16_model,
        test_examples,
        tokenizer,
        device=device,
        precision="fp16",
    )
    qat_triggered = (
        w4a16_accuracy < float(gate["minimum_w4a16_test_accuracy"])
        or fp32_accuracy - w4a16_accuracy
        > float(gate["maximum_accuracy_degradation"])
    )
    qat_metrics: dict[str, Any] = {
        "triggered": qat_triggered,
        "steps": 0,
        "first_loss": None,
        "final_loss": None,
    }
    if qat_triggered:
        fake_model = fake_quantize_gated_linears(
            base_model,
            block_size=block_size,
        )
        qat_metrics = _run_qat(
            fake_model,
            manifest,
            tokenizer,
            model_config=model_config,
            config=qat_config,
            seed=fp16_config.seed + 1,
            device=device,
        )
        w4a16_model, storage = materialize_fake_quant_model(
            fake_model,
            block_size=block_size,
        )
        w4a16_accuracy = tool_decision_accuracy(
            w4a16_model,
            test_examples,
            tokenizer,
            device=device,
            precision="fp16",
        )

    w4a16_model.to(device).eval()
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        w4_output = w4a16_model(
            comparison.input_ids,
            attention_mask=comparison.attention_mask,
        ).logits
    w4_finite = bool(torch.isfinite(w4_output).all())
    w4_path = artifact_dir / "tiny_w4a16.pt"
    torch.save(
        {
            "format": "klara.w4a16-artifact.v1",
            "fp4_format": FP4_FORMAT_VERSION,
            "compute_mode": "dequantized_fp4_weight_matmul",
            "native_fp4_compute": False,
            "model_config": model_config.to_dict(),
            "model_state": {
                key: value.detach().cpu() for key, value in w4a16_model.state_dict().items()
            },
            "storage": storage,
            "qat": qat_metrics,
        },
        w4_path,
    )
    w4_sha256 = hashlib.sha256(w4_path.read_bytes()).hexdigest()
    restored_w4 = TinyDecoderLM(model_config)
    restored_w4, restored_storage = quantize_gated_linears(
        restored_w4,
        block_size=block_size,
    )
    payload = torch.load(w4_path, map_location="cpu", weights_only=False)
    restored_w4.load_state_dict(payload["model_state"], strict=True)
    restored_accuracy = tool_decision_accuracy(
        restored_w4,
        test_examples,
        tokenizer,
        device=device,
        precision="fp16",
    )
    restored_storage = payload["storage"]

    code_round_trip = torch.equal(
        e2m1_encode(e2m1_decode(torch.arange(16, dtype=torch.uint8))),
        torch.arange(16, dtype=torch.uint8),
    )
    nibble_round_trip = all(
        _nibble_round_trip(length) for length in (1, 2, 7, 8)
    )
    accuracy_degradation = fp32_accuracy - w4a16_accuracy
    logit_atol = float(gate["fp16_fp32_logit_atol"])
    maximum_peak = int(gate["maximum_gpu_peak_allocated_bytes"])
    checks = {
        "real_cuda_fp16_amp": fp16_training.device.startswith("cuda")
        and fp16_training.precision == "fp16",
        "fp16_finite": fp16_training.gradients_finite
        and all(
            torch.isfinite(torch.tensor(value))
            for value in (fp16_training.initial_loss, fp16_training.final_loss)
        ),
        "fp16_fp32_within_tolerance": logit_diff <= logit_atol,
        "e2m1_all_codes_round_trip": code_round_trip,
        "nibble_odd_even_round_trip": nibble_round_trip,
        "block_metadata_versioned": storage["format_version"] == FP4_FORMAT_VERSION
        and all(
            item["scale_dtype"] == "float16"
            for item in storage["tensors"].values()
        ),
        "storage_saving": storage["saving_fraction"]
        >= float(gate["minimum_storage_saving_fraction"]),
        "w4a16_finite": w4_finite,
        "w4a16_quality": w4a16_accuracy
        >= float(gate["minimum_w4a16_test_accuracy"])
        and accuracy_degradation <= float(gate["maximum_accuracy_degradation"]),
        "qat_on_quality_failure": (not qat_triggered) or int(qat_metrics["steps"]) > 0,
        "dequantized_compute_disclosed": fp4_config["compute_mode"]
        == "dequantized_fp4_weight_matmul",
        "base_checkpoint_hash_verified": base_details["sha256"] == base_sha256,
        "w4a16_artifact_reload": restored_accuracy == w4a16_accuracy
        and restored_storage == storage,
        "gpu_peak_under_limit": fp16_training.peak_allocated_bytes < maximum_peak,
        "slurm_cuda_execution": bool(os.environ.get("SLURM_JOB_ID")),
    }
    hashes = {
        "config_sha256": stable_sha256(canonical_json(raw)),
        "data_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "teacher_manifest_sha256": manifest.sha256,
        "scorer_sha256": stable_sha256(QUANTIZATION_SCORER_VERSION),
        "base_checkpoint_sha256": base_sha256,
    }
    quality = {
        "fp32_test_accuracy": fp32_accuracy,
        "w4a16_test_accuracy": w4a16_accuracy,
        "accuracy_degradation": accuracy_degradation,
        "qat_triggered": qat_triggered,
        "qat": qat_metrics,
    }
    fp4 = {
        "format_version": FP4_FORMAT_VERSION,
        "block_size": block_size,
        "activation_precision": "fp16",
        "compute_mode": "dequantized_fp4_weight_matmul",
        "native_fp4_compute": False,
        "storage": storage,
        "w4a16_output_finite": w4_finite,
    }
    report = QuantizationReport(
        experiment=str(raw["experiment"]["name"]),
        evaluated_at=datetime.now(UTC).isoformat(),
        source=_source_manifest(),
        fp16={
            "training": fp16_training.to_dict(),
            "logit_max_abs_diff": logit_diff,
            "declared_atol": logit_atol,
            "autocast_dtype": "float16",
            "grad_scaler": True,
        },
        fp4=fp4,
        quality=quality,
        artifacts={
            "fp16_checkpoint": {
                "path": amp_path.as_posix(),
                "sha256": amp_sha256,
            },
            "w4a16": {
                "path": w4_path.as_posix(),
                "sha256": w4_sha256,
            },
        },
        hashes=hashes,
        hardware=_hardware_manifest(),
        checks=checks,
        passed=all(checks.values()),
    )
    (artifact_dir / "manifest.json").write_text(
        json.dumps(
            {"schema_version": "klara.quantization-run.v1", **report.to_dict()},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def _run_qat(
    model: TinyDecoderLM,
    manifest: FrozenTeacherManifest,
    tokenizer: ByteTokenizer,
    *,
    model_config: ModelConfig,
    config: dict[str, Any],
    seed: int,
    device: torch.device,
) -> dict[str, Any]:
    """Run bounded hard-label fake-quant SFT after an actual PTQ quality failure."""

    seed_everything(seed)
    batches = build_sft_batches(
        manifest.split("train"),
        tokenizer,
        sequence_length=model_config.max_sequence_length,
        batch_size=int(config["batch_size"]),
    )
    model.to(device).train()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config["learning_rate"]),
        weight_decay=float(config["weight_decay"]),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=True)
    generator = torch.Generator().manual_seed(seed)
    order: list[int] = []
    index = 0
    losses: list[float] = []
    for _ in range(int(config["steps"])):
        if index >= len(order):
            order = torch.randperm(len(batches), generator=generator).tolist()
            index = 0
        batch = batches[order[index]].to(device)
        index += 1
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=torch.float16):
            output = model(
                batch.input_ids,
                attention_mask=batch.attention_mask,
                labels=batch.labels,
            )
            if output.loss is None:
                raise RuntimeError("QAT did not produce a loss")
            loss = output.loss
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError("QAT produced non-finite loss")
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        if not all(
            parameter.grad is None or bool(torch.isfinite(parameter.grad).all())
            for parameter in model.parameters()
        ):
            raise FloatingPointError("QAT produced non-finite gradients")
        torch.nn.utils.clip_grad_norm_(model.parameters(), float(config["gradient_clip"]))
        scaler.step(optimizer)
        scaler.update()
        losses.append(float(loss.detach().item()))
    return {
        "triggered": True,
        "steps": len(losses),
        "first_loss": losses[0],
        "final_loss": losses[-1],
        "precision": "fp16_amp",
        "grad_scaler": True,
    }


def _nibble_round_trip(length: int) -> bool:
    codes = torch.arange(length, dtype=torch.uint8).remainder(16)
    packed, logical = pack_nibbles(codes)
    return logical == length and torch.equal(unpack_nibbles(packed, logical), codes)


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
    report = run_quantization(args.config, args.corpus, args.artifact_dir)
    args.json_out.write_text(report.to_json(), encoding="utf-8", newline="\n")
    args.markdown_out.write_text(report.to_markdown(), encoding="utf-8", newline="\n")
    print(report.to_json(), end="")
    return 0 if report.passed else 1


def _validate_execution_boundary(execution: dict[str, Any]) -> None:
    required = {key: os.environ.get(key, "") for key in (
        "SLURM_JOB_ID", "SLURMD_NODENAME", "SLURM_JOB_PARTITION",
        "AGENTLADDER_SOURCE_DIR", "AGENTLADDER_SOURCE_BUNDLE_SHA256",
        "AGENTLADDER_PARENT_COMMIT")}
    if bool(execution["require_slurm"]) and any(not value for value in required.values()):
        raise RuntimeError("formal quantization requires HKU Slurm lineage")
    try:
        Path(required["AGENTLADDER_SOURCE_DIR"]).relative_to(
            Path(str(execution["remote_root"])) / "deployments"
        )
    except ValueError as exc:
        raise RuntimeError("quantization source is outside HKU deployments") from exc
    if len(required["AGENTLADDER_SOURCE_BUNDLE_SHA256"]) != 64 or len(required["AGENTLADDER_PARENT_COMMIT"]) != 40:
        raise RuntimeError("source lineage hashes are malformed")


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
        "python": platform.python_version(), "platform": platform.platform(),
        "torch": torch.__version__, "cuda_available": torch.cuda.is_available(),
        "cuda_runtime": torch.version.cuda, "device": torch.cuda.get_device_name(0),
        "device_capability": list(torch.cuda.get_device_capability(0)),
        "vram_bytes": int(torch.cuda.get_device_properties(0).total_memory),
    }


if __name__ == "__main__":
    raise SystemExit(main())
