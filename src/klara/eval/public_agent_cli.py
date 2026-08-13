"""Inspect pinned AgentBench and tau2-bench contracts without inventing scores."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.public_agent import docker_server_status, run_agentbench_contract, run_tau2_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agentbench-checkout", type=Path, required=True)
    parser.add_argument("--tau2-checkout", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agentbench = run_agentbench_contract(args.agentbench_checkout)
    tau2 = run_tau2_contract(args.tau2_checkout)
    report = {
        "schema_version": "klara.public-agent-benchmarks.v1",
        "interpretation": (
            "PASS means the pinned public source/task contracts are reproducible. "
            "Neither benchmark was executed and no Agent score is claimed."
        ),
        "docker": docker_server_status(),
        "benchmarks": {"agentbench": agentbench, "tau2": tau2},
        "passed": agentbench["passed"] and tau2["passed"],
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"passed": report["passed"], "scores_claimed": False}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
