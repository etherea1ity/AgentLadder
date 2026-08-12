"""Machine- and human-readable tiny pretraining gate report."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class PretrainReport:
    """One immutable result rendered to JSON and Markdown."""

    experiment: str
    evaluated_at: str
    source: dict[str, Any]
    model: dict[str, Any]
    train: dict[str, Any]
    hashes: dict[str, str]
    hardware: dict[str, Any]
    result: dict[str, Any]
    cpu_reproducibility: dict[str, Any]
    gpu_smoke: dict[str, Any]
    checkpoint: dict[str, Any]
    checks: dict[str, bool]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the complete canonical report mapping."""

        return {
            "experiment": self.experiment,
            "evaluated_at": self.evaluated_at,
            "source": self.source,
            "model": self.model,
            "train": self.train,
            "hashes": self.hashes,
            "hardware": self.hardware,
            "result": self.result,
            "cpu_reproducibility": self.cpu_reproducibility,
            "gpu_smoke": self.gpu_smoke,
            "checkpoint": self.checkpoint,
            "checks": self.checks,
            "passed": self.passed,
        }

    def to_json(self) -> str:
        """Render stable pretty JSON with a trailing newline."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

    def to_markdown(self) -> str:
        """Render the same experiment result for a human review."""

        status = "PASS" if self.passed else "FAIL"
        result = self.result
        lines = [
            "# Lab B - Repository-Native Tiny Pretraining",
            "",
            f"Status: **{status}**",
            "",
            f"- Experiment: `{self.experiment}`",
            f"- Evaluated at: `{self.evaluated_at}`",
            f"- Parent commit: `{self.source['parent_commit']}`",
            f"- Source bundle SHA-256: `{self.source['bundle_sha256']}`",
            f"- Slurm job: `{self.source['slurm_job_id']}`",
            f"- Device: `{result['device']}`",
            f"- Precision: `{result['precision']}`",
            f"- Parameters: `{result['parameter_count']}`",
            f"- Checkpoint SHA-256: `{self.checkpoint['sha256']}`",
            (
                "- Checkpoint logit max abs diff: "
                f"`{self.checkpoint['logit_max_abs_diff']:.9f}` "
                f"(atol `{self.checkpoint['logit_atol']:.9f}`)"
            ),
            "",
            "## Training Result",
            "",
            "| Measure | Value |",
            "| --- | ---: |",
            f"| initial_loss | {result['initial_loss']:.6f} |",
            f"| final_loss | {result['final_loss']:.6f} |",
            (
                "| loss_reduction_fraction | "
                f"{result['loss_reduction_fraction']:.6f} |"
            ),
            f"| duration_seconds | {result['duration_seconds']:.6f} |",
            f"| peak_allocated_bytes | {result['peak_allocated_bytes']} |",
            "",
            "## Reproducibility And Hardware",
            "",
            f"- CPU hash A: `{self.cpu_reproducibility['first_sha256']}`",
            f"- CPU hash B: `{self.cpu_reproducibility['second_sha256']}`",
            f"- GPU: `{self.gpu_smoke['device']}`",
            f"- GPU smoke peak bytes: `{self.gpu_smoke['peak_allocated_bytes']}`",
            f"- Generated text: `{_markdown_code(result['generated_text'])}`",
            "",
            "## Artifact Hashes",
            "",
            "| Artifact | SHA-256 |",
            "| --- | --- |",
        ]
        for key, value in sorted(self.hashes.items()):
            lines.append(f"| {key} | `{value}` |")
        lines.extend(
            [
                "",
                "## Acceptance Checks",
                "",
                "| Check | Result |",
                "| --- | --- |",
            ]
        )
        for key, value in sorted(self.checks.items()):
            lines.append(f"| {key} | {'PASS' if value else 'FAIL'} |")
        lines.extend(
            [
                "",
                "## Scope",
                "",
                "This is a from-scratch teaching Transformer with byte tokens, "
                "RMSNorm, RoPE, grouped-query causal attention, and a SwiGLU-style "
                "dense feed-forward block. The fixed micro-corpus run proves the "
                "training and checkpoint path; it is not a general language-quality "
                "claim.",
                "",
            ]
        )
        return "\n".join(lines)


def _markdown_code(value: str) -> str:
    """Keep generated text on one safe Markdown code span."""

    return " ".join(value.replace("`", "'").split())
