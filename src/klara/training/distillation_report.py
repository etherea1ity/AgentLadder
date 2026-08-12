"""Single-source report for public-trajectory distillation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class DistillationReport:
    """Immutable Gate 3 result rendered as JSON and Markdown."""

    experiment: str
    evaluated_at: str
    source: dict[str, str]
    dataset: dict[str, Any]
    student: dict[str, Any]
    training: dict[str, Any]
    evidence_control: dict[str, Any]
    checkpoint: dict[str, Any]
    hashes: dict[str, str]
    hardware: dict[str, Any]
    checks: dict[str, bool]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical machine-readable object."""

        return self.__dict__.copy()

    def to_json(self) -> str:
        """Render stable pretty JSON."""

        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"

    def to_markdown(self) -> str:
        """Render the measured result without overstating fixture scope."""

        status = "PASS" if self.passed else "FAIL"
        result = self.training
        lines = [
            "# Lab C - Multi-Teacher Public-Trajectory Distillation",
            "",
            f"Status: **{status}**",
            "",
            f"- Evaluated at: `{self.evaluated_at}`",
            f"- Source bundle SHA-256: `{self.source['bundle_sha256']}`",
            f"- Slurm job: `{self.source['slurm_job_id']}`",
            f"- Teachers: `{', '.join(sorted(self.dataset['teacher_counts']))}`",
            "- Supervision: `hard_label_sft`",
            "- API-teacher KL weight: `0.0`",
            f"- Base checkpoint SHA-256: `{self.student['base_checkpoint_sha256']}`",
            f"- Distilled checkpoint SHA-256: `{self.checkpoint['sha256']}`",
            "",
            "## Dataset Safety",
            "",
            "| Measure | Value |",
            "| --- | ---: |",
            f"| total_examples | {self.dataset['total_examples']} |",
            f"| train_examples | {self.dataset['split_counts']['train']} |",
            f"| validation_examples | {self.dataset['split_counts']['validation']} |",
            f"| test_examples | {self.dataset['split_counts']['test']} |",
            f"| schema_validation_rate | {self.dataset['schema_validation_rate']:.6f} |",
            f"| redaction_pass_rate | {self.dataset['redaction_pass_rate']:.6f} |",
            f"| deduplication_pass_rate | {self.dataset['deduplication_pass_rate']:.6f} |",
            "",
            "## Student Result",
            "",
            "| Measure | Value |",
            "| --- | ---: |",
            f"| pre_sft_tool_decision_accuracy | {result['pre_sft_accuracy']:.6f} |",
            f"| post_sft_tool_decision_accuracy | {result['post_sft_accuracy']:.6f} |",
            f"| validation_accuracy | {result['validation_accuracy']:.6f} |",
            f"| train_loss_first | {result['train_loss_first']:.6f} |",
            f"| train_loss_final | {result['train_loss_final']:.6f} |",
            f"| duration_seconds | {result['duration_seconds']:.6f} |",
            f"| peak_allocated_bytes | {result['peak_allocated_bytes']} |",
            "",
            "## Evidence-Control Regression",
            "",
            f"- Frozen baseline SHA-256: `{self.evidence_control['baseline_sha256']}`",
            f"- Current rerun passed: `{self.evidence_control['current_passed']}`",
            f"- Metrics at or above baseline: `{self.evidence_control['not_regressed']}`",
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
                "## Scope",
                "",
                "This run uses a repository-owned offline public-contract fixture to "
                "prove multi-teacher ingestion, redaction, deduplication, disjoint "
                "splits, hard-label SFT, and evaluation. It is not an online Qwen or "
                "DeepSeek quality benchmark and contains no teacher hidden reasoning, "
                "raw prompts, tool arguments, or raw tool results.",
                "",
            ]
        )
        return "\n".join(lines)
