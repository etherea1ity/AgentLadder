"""Tests for the Chapter 4 CLI harness boundary."""

from __future__ import annotations

import json

from klara.app.cli import main


def test_profile_only_prints_secret_free_run_profile(capsys, monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-leak")

    result = main(["--profile-only"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["schema_version"] == "klara.run-profile.v1"
    assert payload["capability_profile"] == "agent"
    assert payload["visible_tools"] == [
        "current_time",
        "image_generate",
        "web_fetch",
        "web_search",
        "update_activity",
    ]
    assert "must-not-leak" not in json.dumps(payload)
