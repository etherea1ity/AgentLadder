from __future__ import annotations

import json
from pathlib import Path

from klara.eval.suite import build_suite_report, has_frontend_dependency, render_markdown


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_suite_enforces_checkpoint_lineage_and_frontend_boundary(tmp_path: Path) -> None:
    source = {
        "branch": "codex/algorithm-suite-freeze",
        "parent_commit": "a" * 40,
        "dirty_paths": ["src/klara/eval/suite.py"],
    }
    common = {
        "passed": True,
        "checks": {"gate": True},
        "source": {
            "slurm_job_id": "42",
            "bundle_sha256": "b" * 64,
            "parent_commit": "a" * 40,
            "deployment": "/remote/deployments/bundle",
        },
    }
    reports = {
        "lab_a": {
            "passed": True,
            "checks": {"gate": True},
            "dataset": {
                "schema_validation_rate": 1.0,
                "id_linkage_rate": 1.0,
                "leakage_finding_count": 0,
            },
            "metrics": {
                "citation_precision": 1.0,
                "citation_recall": 1.0,
                "abstention_accuracy": 1.0,
            },
        },
        "lab_b": {
            **common,
            "checkpoint": {"sha256": "dense"},
            "hashes": {"data_sha256": "data"},
            "result": {
                "parameter_count": 10,
                "initial_loss": 2.0,
                "final_loss": 1.0,
                "loss_reduction_fraction": 0.5,
            },
        },
        "lab_c": {
            **common,
            "student": {"base_checkpoint_sha256": "dense"},
            "checkpoint": {"sha256": "distilled"},
            "hashes": {"manifest_sha256": "teachers"},
            "dataset": {"teacher_counts": {"qwen": 1, "deepseek": 1}, "total_examples": 2},
            "training": {
                "pre_sft_accuracy": 0.0,
                "post_sft_accuracy": 1.0,
                "validation_accuracy": 1.0,
            },
        },
        "lab_e": {
            **common,
            "architecture": {"moe": {"num_experts": 4, "top_k": 2}, "moe_parameter_count": 20},
            "hashes": {"data_sha256": "data"},
            "moe": {"loss_reduction_fraction": 0.6},
            "routing": {
                "training_corpus": {"max_min_load_ratio": 1.1},
                "balanced_probe": {"max_min_load_ratio": 1.0},
            },
        },
        "lab_h": {
            **common,
            "hashes": {
                "base_checkpoint_sha256": "distilled",
                "data_sha256": "data",
                "teacher_manifest_sha256": "teachers",
            },
            "fp16": {"logit_max_abs_diff": 0.001},
            "fp4": {"storage": {"saving_fraction": 0.7}, "native_fp4_compute": False},
            "quality": {
                "fp32_test_accuracy": 1.0,
                "w4a16_test_accuracy": 1.0,
                "qat_triggered": False,
            },
        },
    }
    paths = {name: _write(tmp_path / f"{name}.json", value) for name, value in reports.items()}
    state_path = _write(tmp_path / "source-state.json", source)
    tests_path = tmp_path / "tests.xml"
    tests_path.write_text(
        '<testsuites><testsuite tests="228" failures="0" errors="0" skipped="1"/></testsuites>',
        encoding="utf-8",
    )

    result = build_suite_report(
        paths, source_state_path=state_path, test_results_path=tests_path
    )

    assert result["passed"]
    assert result["tests"]["passed"] == 227
    assert "There is no" in render_markdown(result)


def test_frontend_dependency_detector_handles_both_path_separators() -> None:
    assert not has_frontend_dependency(("src/klara/eval/suite.py",))
    assert has_frontend_dependency(("apps/web/src/index.ts",))
    assert has_frontend_dependency((r"apps\web\src\index.ts",))
