"""Source- and task-contract checks for official public Agent benchmarks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from klara.eval.public_memory import inspect_public_source


SCHEMA_VERSION = "klara.public-agent-benchmark-contract.v1"
AGENTBENCH_COMMIT = "d1e4a10db08c87075c78972e48ecc182be03e2d5"
TAU2_COMMIT = "79975ac5741e23fbb1d2ac44262d62398a6d87bd"
TAU2_TASK_CONTRACTS = {
    "mock": (10, "0d8bcd14798bf2e6e082432147f62570c57b0897b4e4e388c95bb02ecbe5d8cf"),
    "airline": (50, "ccd8ba737b4cc371415af70151187788f728d6108d0916e73bb4317b40542052"),
    "retail": (114, "8e03ebce7901bd6218e7a7dc3105faa9324091a68058f7fe61c65262868812e8"),
    "telecom": (2285, "37e562e1ae3242577407e1303b1548bc64e7ea68e37d36173e6747990ceaf8a4"),
    "banking_knowledge": (97, "213c7f3e6dc0420b1184ee271e39e38c6ece3c43edfa362db49a560828ebd543"),
}
AGENTBENCH_DATA_CONTRACTS = {
    "data/dbbench/dev.jsonl": 60,
    "data/dbbench/standard.jsonl": 300,
}


def run_agentbench_contract(checkout: Path) -> dict[str, Any]:
    """Validate the pinned low-resource task surface without claiming a score."""

    required = (
        "LICENSE",
        "configs/start_task_lite.yaml",
        "configs/assignments/lite.yaml",
        "configs/tasks/task_assembly.yaml",
        *AGENTBENCH_DATA_CONTRACTS,
    )
    source = inspect_public_source(
        checkout,
        expected_commit=AGENTBENCH_COMMIT,
        required_paths=required,
    )
    rows = {
        relative: _nonempty_lines(checkout / relative)
        for relative in AGENTBENCH_DATA_CONTRACTS
    }
    lite_start = (checkout / "configs/start_task_lite.yaml").read_text(encoding="utf-8")
    lite_assignment = (checkout / "configs/assignments/lite.yaml").read_text(encoding="utf-8")
    checks = {
        "source_commit_and_required_paths": source["passed"],
        "apache_2_license_present": "Apache License" in (checkout / "LICENSE").read_text(encoding="utf-8"),
        "dbbench_row_counts_match": rows == AGENTBENCH_DATA_CONTRACTS,
        "lite_server_includes_dbbench_and_os": all(
            value in lite_start for value in ("dbbench-std", "os-std")
        ),
        "lite_assignment_includes_dbbench_and_os": all(
            value in lite_assignment for value in ("dbbench-std", "os-std")
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "AgentBench",
        "source": {
            "repository": "https://github.com/THUDM/AgentBench",
            "commit": AGENTBENCH_COMMIT,
            "license": "Apache-2.0",
        },
        "source_inspection": source,
        "task_contract": {
            "official_task_definitions": 9,
            "local_low_resource_tasks": ["dbbench-std", "os-std"],
            "data_rows": rows,
        },
        "execution_status": "not_executed",
        "score_status": "not_claimed",
        "requirements_for_score": [
            "start the pinned AgentBench task servers/containers",
            "implement and validate a Klara-compatible AgentBench client adapter",
            "declare a nonzero provider budget and exact model",
            "run official task graders and retain their raw outputs",
        ],
        "checks": checks,
        "passed": all(checks.values()),
    }


def run_tau2_contract(checkout: Path) -> dict[str, Any]:
    """Validate official domains and disclose external-simulator requirements."""

    required = ["LICENSE", "README.md", "pyproject.toml", "docs/evaluation.md"]
    required.extend(
        f"data/tau2/domains/{domain}/tasks.json" for domain in TAU2_TASK_CONTRACTS
    )
    source = inspect_public_source(
        checkout,
        expected_commit=TAU2_COMMIT,
        required_paths=required,
    )
    domains: dict[str, Any] = {}
    for domain, (expected_rows, expected_hash) in TAU2_TASK_CONTRACTS.items():
        path = checkout / "data" / "tau2" / "domains" / domain / "tasks.json"
        tasks = json.loads(path.read_text(encoding="utf-8"))
        ids = [str(item.get("id", "")) for item in tasks]
        domains[domain] = {
            "tasks": len(tasks),
            "sha256": _sha256(path),
            "unique_ids": len(ids) == len(set(ids)) and all(ids),
            "descriptions_present": all(bool(item.get("description")) for item in tasks),
            "user_scenarios_present": all(bool(item.get("user_scenario")) for item in tasks),
            "evaluation_criteria_present": all(bool(item.get("evaluation_criteria")) for item in tasks),
            "contract_matches": len(tasks) == expected_rows and _sha256(path) == expected_hash,
        }
    checks = {
        "source_commit_and_required_paths": source["passed"],
        "mit_license_present": "MIT License" in (checkout / "LICENSE").read_text(encoding="utf-8"),
        "all_domain_contracts_match": all(item["contract_matches"] for item in domains.values()),
        "all_task_ids_unique": all(bool(item["unique_ids"]) for item in domains.values()),
        "all_tasks_have_core_labels": all(
            item["descriptions_present"]
            and item["user_scenarios_present"]
            and item["evaluation_criteria_present"]
            for item in domains.values()
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "tau2-bench",
        "source": {
            "repository": "https://github.com/sierra-research/tau2-bench",
            "commit": TAU2_COMMIT,
            "license": "MIT",
        },
        "source_inspection": source,
        "domains": domains,
        "execution_status": "not_executed",
        "score_status": "not_claimed",
        "requirements_for_score": [
            "install the pinned tau2 environment in an isolated benchmark runtime",
            "build a Klara tau2 agent adapter without changing official tools or tasks",
            "freeze both agent and user-simulator models plus generation budgets",
            "declare a nonzero provider budget and run official trajectory evaluation",
        ],
        "checks": checks,
        "passed": all(checks.values()),
    }


def docker_server_status() -> dict[str, Any]:
    """Return a read-only Docker readiness fact for containerized benchmarks."""

    try:
        completed = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": type(exc).__name__}
    version = completed.stdout.strip()
    return {
        "available": completed.returncode == 0 and bool(version),
        "server_version": version or None,
        "error_present": bool(completed.stderr.strip()),
    }


def _nonempty_lines(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
