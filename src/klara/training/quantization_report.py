"""Single-source report for CUDA FP16 and packed FP4/W4A16."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class QuantizationReport:
    experiment: str
    evaluated_at: str
    source: dict[str, str]
    fp16: dict[str, Any]
    fp4: dict[str, Any]
    quality: dict[str, Any]
    artifacts: dict[str, Any]
    hashes: dict[str, str]
    hardware: dict[str, Any]
    checks: dict[str, bool]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"

    def to_markdown(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [
            "# Lab E - CUDA FP16 And Packed FP4/W4A16",
            "",
            f"Status: **{status}**",
            "",
            f"- Evaluated at: `{self.evaluated_at}`",
            f"- Source bundle SHA-256: `{self.source['bundle_sha256']}`",
            f"- Slurm job: `{self.source['slurm_job_id']}`",
            f"- Base checkpoint SHA-256: `{self.hashes['base_checkpoint_sha256']}`",
            f"- FP4 format: `{self.fp4['format_version']}`",
            "- Compute disclosure: `W4A16 dequantized compute; not native FP4 tensor-core compute`",
            "",
            "## FP16 AMP",
            "",
            "| Measure | Value |",
            "| --- | ---: |",
            f"| initial_loss | {self.fp16['training']['initial_loss']:.6f} |",
            f"| final_loss | {self.fp16['training']['final_loss']:.6f} |",
            f"| duration_seconds | {self.fp16['training']['duration_seconds']:.6f} |",
            f"| peak_allocated_bytes | {self.fp16['training']['peak_allocated_bytes']} |",
            f"| fp16_fp32_logit_max_abs_diff | {self.fp16['logit_max_abs_diff']:.9f} |",
            f"| declared_atol | {self.fp16['declared_atol']:.9f} |",
            "",
            "## Packed FP4 Storage",
            "",
            f"- Quantized gated tensors: `{self.fp4['storage']['tensor_count']}`",
            f"- FP16 baseline bytes: `{self.fp4['storage']['fp16_baseline_bytes']}`",
            f"- Packed codes + scales bytes: `{self.fp4['storage']['fp4_storage_bytes']}`",
            f"- Saving fraction: `{self.fp4['storage']['saving_fraction']:.6f}`",
            f"- Block size: `{self.fp4['block_size']}`",
            f"- QAT triggered: `{self.quality['qat_triggered']}`",
            "",
            "## Held-Out Tool Decisions",
            "",
            "| Model | Accuracy |",
            "| --- | ---: |",
            f"| FP32 | {self.quality['fp32_test_accuracy']:.6f} |",
            f"| W4A16 | {self.quality['w4a16_test_accuracy']:.6f} |",
            f"| degradation | {self.quality['accuracy_degradation']:.6f} |",
            "",
            "## Acceptance Checks",
            "",
            "| Check | Result |",
            "| --- | --- |",
        ]
        for key, value in sorted(self.checks.items()):
            lines.append(f"| {key} | {'PASS' if value else 'FAIL'} |")
        lines.extend(
            [
                "",
                "## Limitations",
                "",
                "The packed artifact stores E2M1 nibbles and FP16 per-block "
                "scales. Inference dequantizes those weights to the activation "
                "dtype before a standard dense matrix multiplication. This is "
                "W4A16 dequantized compute, not native FP4 hardware execution.",
                "",
            ]
        )
        return "\n".join(lines)
