"""Run and persist the real-model evidence, MCP, and team backtests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.live_tooling_backtest import (
    evaluate_live_tooling_backtest,
    render_live_tooling_markdown,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("docs/reports/product/agent-product-live-tooling-backtest.json"),
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=Path("docs/reports/product/agent-product-live-tooling-backtest.md"),
    )
    parser.add_argument(
        "--markdown-en-out",
        type=Path,
        default=Path("docs/reports/product/agent-product-live-tooling-backtest.en.md"),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = evaluate_live_tooling_backtest(root)
    _write(
        args.json_out,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _write(args.markdown_out, render_live_tooling_markdown(report))
    _write(
        args.markdown_en_out,
        render_live_tooling_markdown(report, language="en"),
    )
    print(
        json.dumps(
            {
                "stage": report["stage"],
                "passed": report["passed"],
                **report["metrics"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
