from __future__ import annotations

from pathlib import Path

from klara.eval.memory_benchmark import run_fixture_matrix


ROOT = Path(__file__).resolve().parents[3]


def test_memory_retrieval_matrix_is_fair_and_does_not_fake_competitors(tmp_path) -> None:
    report = run_fixture_matrix(
        ROOT / "tests" / "fixtures" / "memory" / "ch10_retrieval_cases.json",
        tmp_path / "benchmark.sqlite3",
    )

    assert report["same_memory_corpus"] is True
    assert report["same_cases"] is True
    assert set(report["systems"]) == {
        "full_context", "recent", "lexical", "vector", "hybrid", "semantic_recency"
    }
    assert report["systems"]["hybrid"]["critical_top1_accuracy"] == 1.0
    assert report["competitors"]["mem0"]["status"] == "not_executed"
    assert report["competitors"]["mem1"]["status"] == "not_executed"
    assert "does not claim" in report["interpretation"]
