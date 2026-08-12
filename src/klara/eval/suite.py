"""Aggregate the complete algorithm suite without changing stage metrics."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence
import xml.etree.ElementTree as ET


SUITE_SCHEMA_VERSION = "klara.algorithm-suite-freeze.v1"


def build_suite_report(
    report_paths: dict[str, Path],
    *,
    source_state_path: Path,
    test_results_path: Path,
) -> dict[str, Any]:
    """Validate the five immutable gate reports and return one freeze object."""

    reports = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in report_paths.items()
    }
    required = {"lab_a", "lab_b", "lab_c", "lab_e", "lab_h"}
    if set(reports) != required:
        raise ValueError(f"suite requires exactly {sorted(required)}")
    source_state = json.loads(source_state_path.read_text(encoding="utf-8"))
    test_summary = _read_test_summary(test_results_path)

    stage_checks = {
        name: bool(report.get("passed"))
        and bool(report.get("checks"))
        and all(bool(value) for value in report["checks"].values())
        for name, report in reports.items()
    }
    cloud_reports = [reports[name] for name in ("lab_b", "lab_c", "lab_e", "lab_h")]
    cloud_sources = [report["source"] for report in cloud_reports]
    jobs = {source["slurm_job_id"] for source in cloud_sources}
    bundles = {source["bundle_sha256"] for source in cloud_sources}
    parents = {source["parent_commit"] for source in cloud_sources}
    deployments = {source["deployment"] for source in cloud_sources}
    dirty_paths = tuple(str(path) for path in source_state.get("dirty_paths", ()))

    lab_b = reports["lab_b"]
    lab_c = reports["lab_c"]
    lab_e = reports["lab_e"]
    lab_h = reports["lab_h"]
    checks = {
        "all_stage_reports_pass": all(stage_checks.values()),
        "single_slurm_job": len(jobs) == 1,
        "single_source_bundle": len(bundles) == 1,
        "single_parent_commit": len(parents) == 1,
        "single_deployment": len(deployments) == 1,
        "source_state_matches_reports": source_state.get("parent_commit")
        in parents
        and source_state.get("branch") == "codex/algorithm-suite-freeze",
        "dense_to_distillation_checkpoint_lineage": (
            lab_c["student"]["base_checkpoint_sha256"]
            == lab_b["checkpoint"]["sha256"]
        ),
        "distillation_to_fp4_checkpoint_lineage": (
            lab_h["hashes"]["base_checkpoint_sha256"]
            == lab_c["checkpoint"]["sha256"]
        ),
        "moe_comparison_uses_dense_data": (
            lab_e["hashes"]["data_sha256"] == lab_b["hashes"]["data_sha256"]
        ),
        "precision_run_uses_dense_data": (
            lab_h["hashes"]["data_sha256"] == lab_b["hashes"]["data_sha256"]
        ),
        "teacher_manifest_lineage": (
            lab_h["hashes"]["teacher_manifest_sha256"]
            == lab_c["hashes"]["manifest_sha256"]
        ),
        "full_python_suite_passed": test_summary["passed"] > 0
        and test_summary["failures"] == 0
        and test_summary["errors"] == 0,
        "no_frontend_dependency_added": not has_frontend_dependency(dirty_paths),
    }
    artifacts = {
        name: {
            "path": report_paths[name].as_posix(),
            "sha256": _sha256(report_paths[name]),
        }
        for name in sorted(report_paths)
    }
    metrics = {
        "evidence": {
            "schema_validation_rate": reports["lab_a"]["dataset"][
                "schema_validation_rate"
            ],
            "id_linkage_rate": reports["lab_a"]["dataset"]["id_linkage_rate"],
            "leakage_findings": reports["lab_a"]["dataset"][
                "leakage_finding_count"
            ],
            "citation_precision": reports["lab_a"]["metrics"][
                "citation_precision"
            ],
            "citation_recall": reports["lab_a"]["metrics"]["citation_recall"],
            "abstention_accuracy": reports["lab_a"]["metrics"][
                "abstention_accuracy"
            ],
        },
        "dense": {
            "parameters": lab_b["result"]["parameter_count"],
            "initial_loss": lab_b["result"]["initial_loss"],
            "final_loss": lab_b["result"]["final_loss"],
            "loss_reduction_fraction": lab_b["result"][
                "loss_reduction_fraction"
            ],
        },
        "distillation": {
            "teachers": sorted(lab_c["dataset"]["teacher_counts"]),
            "examples": lab_c["dataset"]["total_examples"],
            "pre_sft_accuracy": lab_c["training"]["pre_sft_accuracy"],
            "post_sft_accuracy": lab_c["training"]["post_sft_accuracy"],
            "validation_accuracy": lab_c["training"]["validation_accuracy"],
        },
        "moe": {
            "experts": lab_e["architecture"]["moe"]["num_experts"],
            "top_k": lab_e["architecture"]["moe"]["top_k"],
            "parameters": lab_e["architecture"]["moe_parameter_count"],
            "loss_reduction_fraction": lab_e["moe"]["loss_reduction_fraction"],
            "training_load_ratio": lab_e["routing"]["training_corpus"][
                "max_min_load_ratio"
            ],
            "balanced_load_ratio": lab_e["routing"]["balanced_probe"][
                "max_min_load_ratio"
            ],
        },
        "precision": {
            "fp16_fp32_logit_max_abs_diff": lab_h["fp16"][
                "logit_max_abs_diff"
            ],
            "fp4_storage_saving_fraction": lab_h["fp4"]["storage"][
                "saving_fraction"
            ],
            "fp32_test_accuracy": lab_h["quality"]["fp32_test_accuracy"],
            "w4a16_test_accuracy": lab_h["quality"]["w4a16_test_accuracy"],
            "native_fp4_compute": lab_h["fp4"]["native_fp4_compute"],
            "qat_triggered": lab_h["quality"]["qat_triggered"],
        },
    }
    return {
        "schema_version": SUITE_SCHEMA_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "source": {
            "branch": source_state["branch"],
            "parent_commit": next(iter(parents)),
            "bundle_sha256": next(iter(bundles)),
            "deployment": next(iter(deployments)),
            "slurm_job_id": next(iter(jobs)),
        },
        "stage_checks": stage_checks,
        "checks": checks,
        "metrics": metrics,
        "artifacts": artifacts,
        "tests": test_summary,
        "passed": all(checks.values()),
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render the suite object without inventing a cross-task aggregate score."""

    evidence = report["metrics"]["evidence"]
    dense = report["metrics"]["dense"]
    distill = report["metrics"]["distillation"]
    moe = report["metrics"]["moe"]
    precision = report["metrics"]["precision"]
    lines = [
        "# AgentLadder Algorithm Suite Freeze",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- Slurm job: `{report['source']['slurm_job_id']}`",
        f"- Source bundle: `{report['source']['bundle_sha256']}`",
        f"- Parent commit: `{report['source']['parent_commit']}`",
        f"- Full Python suite: `{report['tests']['passed']} passed, {report['tests']['skipped']} skipped`",
        "- Frontend dependency added: `False`",
        "",
        "## Measured Matrix",
        "",
        "| Workstream | Reproduced result |",
        "| --- | --- |",
        f"| Evidence/eval | schema {evidence['schema_validation_rate']:.3f}; linkage {evidence['id_linkage_rate']:.3f}; leaks {evidence['leakage_findings']}; citation P/R {evidence['citation_precision']:.3f}/{evidence['citation_recall']:.3f}; abstention {evidence['abstention_accuracy']:.3f} |",
        f"| Tiny dense | {dense['parameters']} params; loss {dense['initial_loss']:.6f} -> {dense['final_loss']:.6f}; reduction {dense['loss_reduction_fraction']:.3%} |",
        f"| Distillation | {','.join(distill['teachers'])}; {distill['examples']} public examples; held-out accuracy {distill['pre_sft_accuracy']:.3f} -> {distill['post_sft_accuracy']:.3f} |",
        f"| Sparse MoE | {moe['experts']} experts, top-{moe['top_k']}; {moe['parameters']} params; loss reduction {moe['loss_reduction_fraction']:.3%}; load ratio {moe['training_load_ratio']:.3f} |",
        f"| FP16/FP4 | logit max diff {precision['fp16_fp32_logit_max_abs_diff']:.9f}; packed saving {precision['fp4_storage_saving_fraction']:.3%}; W4A16 accuracy {precision['w4a16_test_accuracy']:.3f} |",
        "",
        "## Acceptance Checks",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    for key, value in sorted(report["checks"].items()):
        lines.append(f"| {key} | {'PASS' if value else 'FAIL'} |")
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "Each value preserves its stage-specific scorer and fixture. There is no "
            "synthetic overall quality score. The distillation result is an offline "
            "public-contract fixture result, the dense/MoE runs are micro-corpus "
            "training checks, and W4A16 uses packed FP4 storage with dequantized "
            "dense compute rather than native FP4 tensor-core execution.",
            "",
        ]
    )
    return "\n".join(lines)


def has_frontend_dependency(paths: Sequence[str]) -> bool:
    """Return whether a packaged dirty path enters the excluded web frontend."""

    return any(path.replace("\\", "/").startswith("apps/web/") for path in paths)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("lab-a", "lab-b", "lab-c", "lab-e", "lab-h"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--source-state", type=Path, required=True)
    parser.add_argument("--test-results", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_suite_report(
        {
            "lab_a": args.lab_a,
            "lab_b": args.lab_b,
            "lab_c": args.lab_c,
            "lab_e": args.lab_e,
            "lab_h": args.lab_h,
        },
        source_state_path=args.source_state,
        test_results_path=args.test_results,
    )
    args.json_out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    args.markdown_out.write_text(
        render_markdown(report), encoding="utf-8", newline="\n"
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_test_summary(path: Path) -> dict[str, int]:
    """Read deterministic counts from pytest JUnit XML, not console wording."""

    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise ValueError("test results contain no testsuite element")
    tests = int(suite.attrib.get("tests", "0"))
    failures = int(suite.attrib.get("failures", "0"))
    errors = int(suite.attrib.get("errors", "0"))
    skipped = int(suite.attrib.get("skipped", "0"))
    passed = tests - failures - errors - skipped
    if tests < 1 or passed < 0:
        raise ValueError("test result counts are invalid")
    return {
        "tests": tests,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


if __name__ == "__main__":
    raise SystemExit(main())
