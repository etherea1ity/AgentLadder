"""Write the aggregate Agent product live-backtest report from one result object."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.live_backtest_report import (
    build_live_backtest_report,
    render_live_backtest_markdown,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument("--markdown-en-out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_live_backtest_report(args.repository_root.resolve())
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    args.markdown_out.write_text(
        render_live_backtest_markdown(report, language="zh"),
        encoding="utf-8",
        newline="\n",
    )
    args.markdown_en_out.write_text(
        render_live_backtest_markdown(report, language="en"),
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"passed": report["passed"], "status": report["status"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
