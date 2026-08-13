"""Synthetic unit tests for public Agent benchmark source adapters."""

from __future__ import annotations

import hashlib
import json

from klara.eval.public_agent import run_tau2_contract


def test_tau2_contract_validates_labels_without_executing_scores(tmp_path, monkeypatch) -> None:
    for relative, content in {
        "LICENSE": "MIT License",
        "README.md": "fixture",
        "pyproject.toml": "fixture",
        "docs/evaluation.md": "fixture",
    }.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    contracts = {}
    for domain in ("mock", "airline", "retail", "telecom", "banking_knowledge"):
        path = tmp_path / "data" / "tau2" / "domains" / domain / "tasks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [
                    {
                        "id": domain,
                        "description": "d",
                        "user_scenario": {"instructions": "fixture"},
                        "evaluation_criteria": {"communicate_info": ["fixture"]},
                    }
                ]
            ),
            encoding="utf-8",
        )
        contracts[domain] = (1, hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr("klara.eval.public_agent.TAU2_COMMIT", "fixture")
    monkeypatch.setattr("klara.eval.public_agent.TAU2_TASK_CONTRACTS", contracts)
    monkeypatch.setattr(
        "klara.eval.public_agent.inspect_public_source",
        lambda *args, **kwargs: {
            "expected_commit": "fixture",
            "actual_commit": "fixture",
            "commit_matches": True,
            "required_paths": {},
            "passed": True,
        },
    )

    report = run_tau2_contract(tmp_path)

    assert report["passed"]
    assert report["execution_status"] == "not_executed"
    assert report["score_status"] == "not_claimed"
