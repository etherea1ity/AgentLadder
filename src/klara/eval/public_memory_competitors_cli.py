"""Write official memory competitor readiness contracts as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.public_memory_competitors import run_memory_competitor_contracts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mem0-checkout", type=Path, required=True)
    parser.add_argument("--mem1-checkout", type=Path, required=True)
    parser.add_argument("--beam-checkout", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_memory_competitor_contracts(
        mem0_checkout=args.mem0_checkout,
        mem1_checkout=args.mem1_checkout,
        beam_checkout=args.beam_checkout,
    )
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
