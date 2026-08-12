"""Behavior tests for the product-baseline audit helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[3] / "scripts" / "audit_product_baseline.py"
SPEC = importlib.util.spec_from_file_location("audit_product_baseline", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_branch_roles_keep_legacy_rag_as_design_source() -> None:
    role, decision = MODULE._role("origin/rag")

    assert role == "legacy_design_source"
    assert "never merge" in decision


def test_capability_audit_does_not_call_missing_product_features_complete() -> None:
    statuses = {item["id"]: item["status"] for item in MODULE._capabilities()}

    assert statuses["ch04-harness-config"] == "partial"
    assert statuses["ch05-todo-planning"] == "missing"
    assert statuses["ch11-formal-rag"] == "deferred_by_scope"
    assert statuses["model-kv-cache"] == "missing"


def test_initial_ledger_keeps_only_baseline_green() -> None:
    ledger = MODULE._ledger_object("codex/agent-product-baseline", "a" * 64)
    statuses = {item["id"]: item["status"] for item in ledger["objectives"]}

    assert statuses["phase-0a-baseline"] == "passed"
    assert statuses["phase-0b-agent-eval-contract"] == "pending"
    assert statuses["agent-product-freeze"] == "pending"
    assert statuses["ch11-formal-rag"] == "deferred_by_scope"


def test_baseline_and_ledger_render_as_bilingual_pairs() -> None:
    report = {
        "passed": True,
        "source": {
            "branch": "codex/agent-product-baseline",
            "authoritative_parent": MODULE.AUTHORITATIVE_PARENT,
            "source_bundle_sha256": "a" * 64,
        },
        "branch_documentation_matrix": [],
        "distinct_document_blobs": 0,
        "tests": {
            "python": {"passed": 1, "skipped": 0},
            "frontend": {"passed": 1},
        },
        "capabilities": [],
    }
    ledger = MODULE._ledger_object("codex/agent-product-baseline", "a" * 64)

    assert "English" in MODULE.render_baseline(report)
    assert "Chinese" in MODULE.render_baseline(report, language="en")
    assert "English" in MODULE.render_ledger(ledger)
    assert "Chinese" in MODULE.render_ledger(ledger, language="en")
