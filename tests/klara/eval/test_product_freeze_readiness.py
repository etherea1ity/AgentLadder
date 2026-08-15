"""Behavior tests for Agent Product Freeze readiness reconciliation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from klara.eval.product_freeze_readiness import (
    build_report,
    render_ledger,
    render_report,
)


ROOT = Path(__file__).parents[3]
MANIFEST = ROOT / "config/stages/agent-product-freeze-readiness.manifest.json"
SOURCE_COMMIT = "0d3f3d5b61a2a374f504e0f8407f72de14d49cc7"


def _build() -> tuple[dict[str, object], dict[str, object]]:
    return build_report(
        ROOT,
        manifest_path=MANIFEST,
        source_commit=SOURCE_COMMIT,
        python_tests_collected=513,
        python_tests_skipped=2,
        web_tests=71,
        web_test_files=20,
        web_build_passed=True,
    )


def test_readiness_selects_fresh_split_without_erasing_historical_failure() -> None:
    report, ledger = _build()

    assert report["stage_passed"] is True
    assert report["agent_product_freeze_allowed"] is False
    assert report["model_training_allowed"] is False
    assert report["memory"]["fresh_split_offset"] == 10
    assert report["memory"]["historical_failed_replay"]["preserved"] is True
    assert report["memory"]["agent_recall_delta"] > 0
    assert report["memory"]["agent_f1_delta"] < 0
    assert report["claims"]["external_memory_competitor_superiority"] is False
    statuses = {item["id"]: item["status"] for item in ledger["objectives"]}
    assert statuses["agent-product-freeze-readiness"] == "passed"
    assert statuses["agent-product-freeze"] == "blocked_external"
    assert statuses["model-kv-cache"] == "pending"
    assert statuses["model-integration-freeze"] == "pending"


def test_readiness_fails_closed_when_a_frozen_hash_changes(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["inputs"][0]["sha256"] = "0" * 64
    changed_manifest = tmp_path / "manifest.json"
    changed_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="input hash drift"):
        build_report(
            ROOT,
            manifest_path=changed_manifest,
            source_commit=SOURCE_COMMIT,
            python_tests_collected=513,
            python_tests_skipped=2,
            web_tests=71,
            web_test_files=20,
            web_build_passed=True,
        )


def test_readiness_and_ledger_render_as_bilingual_pairs() -> None:
    report, ledger = _build()

    zh = render_report(report)
    en = render_report(report, language="en")
    ledger_zh = render_ledger(ledger)
    ledger_en = render_ledger(ledger, language="en")

    assert "(./agent-product-freeze-readiness.en.md)" in zh
    assert "(./agent-product-freeze-readiness.md)" in en
    assert "总体领先声明" in zh
    assert "superiority claim" in en
    assert "(./completion-ledger.en.md)" in ledger_zh
    assert "(./completion-ledger.md)" in ledger_en
