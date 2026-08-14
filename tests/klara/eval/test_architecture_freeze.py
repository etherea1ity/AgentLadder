from __future__ import annotations

import json
from pathlib import Path

from klara.eval.architecture_freeze import CHAPTER_GATES, build_architecture_freeze_report


def test_architecture_freeze_requires_all_runtime_and_historical_evidence(tmp_path) -> None:
    repository_root = Path(__file__).parents[3]
    gates = tmp_path / "gates"
    gates.mkdir()
    for name in CHAPTER_GATES:
        (gates / f"{name}.json").write_text(
            json.dumps({"passed": True, "gate_kind": f"gate-{name}"}), encoding="utf-8"
        )
    audit = tmp_path / "audit.json"
    audit.write_text(
        json.dumps(
            {
                "branch_count": 34,
                "summary": {"compile_passed": 34, "pytest_passed": 33},
                "interpretation": {"live_provider_calls": False},
            }
        ),
        encoding="utf-8",
    )

    report = build_architecture_freeze_report(
        repository_root,
        gates,
        audit,
        python_tests_collected=494,
        python_tests_skipped=2,
        web_test_files=20,
        web_tests=71,
        web_build_passed=True,
    )

    assert report["passed"]
    assert report["status"] == "architecture_frozen_live_behavior_pending"
    assert report["next_gate"].startswith("live DeepSeek")
