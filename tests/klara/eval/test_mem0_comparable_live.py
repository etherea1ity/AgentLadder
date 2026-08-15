"""Deterministic tests for the official-Mem0 same-control adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from klara.eval import mem0_comparable_live as mem0_live
from klara.eval import mem0_comparable_server as mem0_server
from klara.eval.mem0_comparable_live import (
    MEM0_PR_HEAD,
    _aggregate,
    _load_official_ingestion_turns,
    render_mem0_report,
    update_product_freeze_artifacts,
)


def test_http_client_survives_more_than_four_recoverable_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"status":"ok"}'

    calls = 0

    def fake_urlopen(*_: object, **__: object) -> Response:
        nonlocal calls
        calls += 1
        if calls <= 5:
            raise mem0_live.HTTPError("https://example.test", 500, "bad", {}, None)
        return Response()

    monkeypatch.setattr(mem0_live, "urlopen", fake_urlopen)
    monkeypatch.setattr(mem0_live, "sleep", lambda _: None)

    result = mem0_live.Mem0HttpClient("https://example.test").health()

    assert result == {"status": "ok"}
    assert calls == 6


def test_strict_json_boundary_surfaces_failure_hidden_by_pinned_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeLlm:
        calls = 0

        def generate_response(self, *_: object, **__: object) -> str:
            self.calls += 1
            return "{malformed"

    class FakeMemory:
        def __init__(self) -> None:
            self.llm = FakeLlm()

        def add(self, *_: object, **__: object) -> dict:
            try:
                self.llm.generate_response(
                    response_format={"type": "json_object"}
                )
            except RuntimeError:
                # This matches the immutable PR head: it catches the provider
                # exception and falsely turns it into an empty result.
                return {"results": []}
            return {"results": [{"memory": "unexpected"}]}

    monkeypatch.setattr(mem0_server, "_EXTRACTION_JSON_RETRIES", 0)
    monkeypatch.setattr(mem0_server, "_EXTRACTION_JSON_REQUEST_FAILURES", 0)
    monkeypatch.setattr(mem0_server, "sleep", lambda _: None)
    monkeypatch.setattr(
        mem0_server,
        "_parse_json_object",
        lambda _: (_ for _ in ()).throw(ValueError("invalid")),
    )
    memory = FakeMemory()
    mem0_server._install_strict_extraction_retry(memory)
    request = mem0_server.AddRequest(
        messages=[{"role": "user", "content": "safe public test"}],
        user_id="test-user",
    )

    with pytest.raises(
        RuntimeError, match="mem0_extraction_json_invalid_after_retries"
    ):
        mem0_server._run_add_with_strict_boundary(memory, request)

    assert memory.llm.calls == 3
    assert mem0_server._EXTRACTION_JSON_RETRIES == 2
    assert mem0_server._EXTRACTION_JSON_REQUEST_FAILURES == 1


def test_official_ingestion_turns_preserve_role_time_and_image(tmp_path: Path) -> None:
    dataset = [
        {
            "conversation": {
                "speaker_a": "Alice",
                "speaker_b": "Bob",
                "session_1_date_time": "1:56 pm on 8 May, 2023",
                "session_1": [
                    {
                        "dia_id": "D1:1",
                        "speaker": "Alice",
                        "text": "Look",
                        "query": "a bird",
                        "blip_caption": "a cobalt bird",
                    },
                    {
                        "dia_id": "D1:2",
                        "speaker": "Bob",
                        "text": "Nice",
                    },
                ],
            },
            "qa": [],
        }
    ]
    path = tmp_path / "locomo.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    turns = _load_official_ingestion_turns(path)

    assert [turn.role for turn in turns] == ["user", "assistant"]
    assert turns[0].ingest_key == "locomo-00:D1:1"
    assert turns[0].occurred_at == "2023-05-08T13:56:00+00:00"
    assert "The image shows: a cobalt bird" in turns[0].content
    assert turns[1].turn_index == 1


def test_aggregate_keeps_failures_and_runtime_metrics_visible() -> None:
    rows = [
        {
            "category": "1",
            "official_f1": 0.5,
            "exact_match": False,
            "evidence_recall_at_k": 1.0,
            "context_items": 20,
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "retrieval_latency_ms": 20,
            "latency_ms": 100,
            "strange_response_p0": None,
            "error": None,
        },
        {
            "category": "2",
            "official_f1": 0.0,
            "exact_match": False,
            "evidence_recall_at_k": 0.0,
            "context_items": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "retrieval_latency_ms": 40,
            "latency_ms": 200,
            "strange_response_p0": "empty_answer",
            "error": {"type": "ModelCallError", "code": "provider_timeout"},
        },
    ]

    result = _aggregate(rows)

    assert result["completed"] == 1
    assert result["errors"] == 1
    assert result["error_codes"] == {"provider_timeout": 1}
    assert result["official_f1"] == 0.25
    assert result["evidence_recall_at_k"] == 0.5
    assert result["strange_response_p0"] == 1


def test_freeze_reconciliation_removes_only_mem0_blocker(tmp_path: Path) -> None:
    product = tmp_path / "docs/reports/product"
    product.mkdir(parents=True)
    readiness = {
        "evaluated_at": "old",
        "mandatory_blockers": [
            {"id": "independent-model-judge", "detail": "judge missing"},
            {"id": "blind-human-review", "detail": "human labels missing"},
            {"id": "official-mem0-comparison", "detail": "old Mem0 defect"},
        ],
        "product_freeze_checks": {
            "official_mem0_same_control_comparison_green": False
        },
        "memory": {},
        "claims": {"external_memory_competitor_superiority": False},
        "stage_verification": {
            "python_tests_collected": 513,
            "python_tests_skipped": 2,
        },
        "agent_product_freeze_allowed": False,
        "model_training_allowed": False,
        "status": "stage_passed_product_freeze_blocked",
        "expansion_gaps": [{"id": "mem1", "detail": "MEM1 pending"}],
    }
    ledger = {
        "updated_at": "old",
        "objectives": [
            {
                "id": "agent-product-benchmarks",
                "metrics": {},
                "remaining_failures": [],
            },
            {
                "id": "agent-product-freeze",
                "status": "blocked_external",
                "evidence": {"training_allowed": False},
                "remaining_failures": [],
            },
        ],
    }
    (product / "agent-product-freeze-readiness.json").write_text(
        json.dumps(readiness), encoding="utf-8"
    )
    (product / "completion-ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )
    report = _sample_report()

    updated_readiness, updated_ledger = update_product_freeze_artifacts(
        tmp_path,
        mem0_report=report,
        source_commit="a" * 40,
        python_tests_collected=517,
        python_tests_skipped=2,
    )

    assert [item["id"] for item in updated_readiness["mandatory_blockers"]] == [
        "independent-model-judge",
        "blind-human-review",
    ]
    assert updated_readiness["agent_product_freeze_allowed"] is False
    assert updated_readiness["model_training_allowed"] is False
    assert (
        updated_readiness["product_freeze_checks"]
        ["official_mem0_same_control_comparison_green"]
        is True
    )
    objectives = {item["id"]: item for item in updated_ledger["objectives"]}
    assert objectives["mem0-comparable-reproduction"]["status"] == "passed"
    assert objectives["agent-product-freeze"]["status"] == "blocked_external"
    assert objectives["agent-product-freeze"]["evidence"]["training_allowed"] is False


def test_markdown_preserves_same_control_claim_boundary() -> None:
    report = _sample_report()

    rendered = render_mem0_report(report, language="en")

    assert MEM0_PR_HEAD in rendered
    assert "Mem0 OSS v3 PR #4805" in rendered
    assert "not a general superiority claim" in rendered


def _sample_report() -> dict:
    system = {
        "cases": 100,
        "completed": 100,
        "official_f1": 0.4,
        "exact_match": 0.2,
        "evidence_recall_at_k": 0.7,
    }
    return {
        "schema_version": "klara.mem0-comparable-reproduction.v2",
        "evaluated_at": "2026-08-15T00:00:00+00:00",
        "passed": True,
        "source": {"mem0": {"pull_request_head": MEM0_PR_HEAD}},
        "selection": {"selected_questions": 100},
        "systems": {
            "mem0_v3_pr4805": system,
            "klara_loop_memory_agent": {**system, "official_f1": 0.45},
            "klara_direct_hybrid": {**system, "official_f1": 0.46},
        },
        "comparison": {
            "agent_f1_delta_vs_mem0": 0.05,
            "agent_recall_delta_vs_mem0": 0.0,
            "frozen_same_control_agent_outperforms_mem0_on_f1": True,
            "frozen_same_control_agent_outperforms_mem0_on_recall": False,
        },
        "checks": {"source_pinned": True},
        "harness_deviations": ["Exact PR head replaces the deleted branch."],
        "claim_boundary": [
            "A win on this frozen 100-question split is not a general superiority claim."
        ],
    }
