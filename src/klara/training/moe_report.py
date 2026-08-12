"""Single-source report for the tiny sparse MoE gate."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class MoEReport:
    """Immutable dense/MoE comparison and routing evidence."""

    experiment: str
    evaluated_at: str
    source: dict[str, str]
    fairness: dict[str, Any]
    architecture: dict[str, Any]
    dense: dict[str, Any]
    moe: dict[str, Any]
    routing: dict[str, Any]
    checkpoints: dict[str, Any]
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
        balanced = self.routing["balanced_probe"]
        heldout = self.routing["training_corpus"]
        lines = [
            "# Lab D - Four-Expert Top-2 Sparse MoE",
            "",
            f"Status: **{status}**",
            "",
            f"- Evaluated at: `{self.evaluated_at}`",
            f"- Source bundle SHA-256: `{self.source['bundle_sha256']}`",
            f"- Slurm job: `{self.source['slurm_job_id']}`",
            "- Experts: `4`",
            "- Routing: `token-level top-2 distinct`",
            f"- Scorer SHA-256: `{self.hashes['scorer_sha256']}`",
            "",
            "## Fair Dense/MoE Comparison",
            "",
            "| Measure | Dense | MoE |",
            "| --- | ---: | ---: |",
            f"| initial_loss | {self.dense['initial_loss']:.6f} | {self.moe['initial_loss']:.6f} |",
            f"| final_loss | {self.dense['final_loss']:.6f} | {self.moe['final_loss']:.6f} |",
            f"| loss_reduction_fraction | {self.dense['loss_reduction_fraction']:.6f} | {self.moe['loss_reduction_fraction']:.6f} |",
            f"| parameter_count | {self.dense['parameter_count']} | {self.moe['parameter_count']} |",
            f"| duration_seconds | {self.dense['duration_seconds']:.6f} | {self.moe['duration_seconds']:.6f} |",
            f"| peak_allocated_bytes | {self.dense['peak_allocated_bytes']} | {self.moe['peak_allocated_bytes']} |",
            "",
            "## Routing Diagnostics",
            "",
            f"- Balanced expert loads: `{balanced['expert_loads']}`",
            f"- Balanced max/min ratio: `{balanced['max_min_load_ratio']:.6f}`",
            f"- Balanced router entropy: `{balanced['router_entropy']:.6f}`",
            f"- Training-corpus expert loads: `{heldout['expert_loads']}`",
            f"- Training-corpus max/min ratio: `{heldout['max_min_load_ratio']:.6f}`",
            f"- Training-corpus router entropy: `{heldout['router_entropy']:.6f}`",
            f"- Selected top-2 weight sum mean: `{heldout['selected_weight_sum_mean']:.9f}`",
            f"- Router z-loss: `{heldout['router_z_loss']:.6f}`",
            f"- Router balance loss: `{heldout['router_balance_loss']:.6f}`",
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
                "Both models use the same fixed micro-corpus, seed, step budget, "
                "batching, optimizer settings, precision, and scorer. This proves "
                "the sparse routing and bounded training path; it is not a broad "
                "language-quality benchmark.",
                "",
            ]
        )
        return "\n".join(lines)
