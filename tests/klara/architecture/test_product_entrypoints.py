"""Architecture checks that prevent product entrypoints bypassing the harness."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[3]


def test_api_run_service_uses_harness_without_constructing_core_loop() -> None:
    source = (ROOT / "apps/api/services/run_service.py").read_text(encoding="utf-8")

    assert "KlaraHarness(" in source
    assert "KlaraLoop(" not in source


def test_cli_uses_harness_without_constructing_core_loop() -> None:
    source = (ROOT / "src/klara/app/cli.py").read_text(encoding="utf-8")

    assert "KlaraHarness(" in source
    assert "KlaraLoop(" not in source
