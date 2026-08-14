"""Run and persist the live Qwen-to-DeepSeek provider fallback gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.provider_fallback_live import (
    evaluate_provider_fallback_live,
    render_provider_fallback_live_markdown,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("docs/reports/product/ch08-provider-live-fallback.json"),
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=Path("docs/reports/product/ch08-provider-live-fallback.md"),
    )
    parser.add_argument(
        "--markdown-en-out",
        type=Path,
        default=Path("docs/reports/product/ch08-provider-live-fallback.en.md"),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = evaluate_provider_fallback_live(root)
    _write(
        args.json_out,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _write(args.markdown_out, render_provider_fallback_live_markdown(report))
    _write(
        args.markdown_en_out,
        render_provider_fallback_live_markdown(report, language="en"),
    )
    print(
        json.dumps(
            {
                "stage": report["stage"],
                "passed": report["passed"],
                "requested_model": report["requested_model"],
                "model_used": report["model_used"],
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
