"""Tests for bilingual documentation structure and link validation."""

from __future__ import annotations

from pathlib import Path

from klara.eval.documentation import validate_pair


def test_document_pair_requires_matching_structure_and_links(tmp_path: Path) -> None:
    asset = tmp_path / "image.svg"
    asset.write_text("<svg></svg>", encoding="utf-8")
    chinese = tmp_path / "guide.md"
    english = tmp_path / "guide.en.md"
    chinese.write_text(
        "# 指南\n\n语言：中文 | [English](./guide.en.md)\n\n![图](./image.svg)\n",
        encoding="utf-8",
    )
    english.write_text(
        "# Guide\n\nLanguage: [Chinese](./guide.md) | English\n\n![Image](./image.svg)\n",
        encoding="utf-8",
    )

    result = validate_pair(tmp_path, chinese, english)

    assert result.passed


def test_document_pair_reports_missing_local_target(tmp_path: Path) -> None:
    chinese = tmp_path / "guide.md"
    english = tmp_path / "guide.en.md"
    chinese.write_text("# 指南\n\n[English](./guide.en.md)\n\n[缺失](./none.md)\n", encoding="utf-8")
    english.write_text("# Guide\n\n[Chinese](./guide.md)\n", encoding="utf-8")

    result = validate_pair(tmp_path, chinese, english)

    assert not result.passed
    assert any("none.md" in failure for failure in result.failures)
