"""Contract checks for official competitor-source handling."""

from __future__ import annotations

from klara.eval.public_memory_competitors import _jsonl_count


def test_jsonl_count_ignores_blank_lines(tmp_path) -> None:
    path = tmp_path / "demo.jsonl"
    path.write_text('{"a":1}\n\n{"a":2}\n', encoding="utf-8")

    assert _jsonl_count(path) == 2
