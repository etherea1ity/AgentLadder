"""Write bounded real-model evidence for the main-Agent runtime integration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.runtime_integration_live import DEFAULT_MODEL, evaluate_runtime_integration_live


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate_runtime_integration_live(
        args.repository_root.resolve(),
        model=args.model,
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"stage": report["stage"], "passed": report["passed"], **report["metrics"]}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
