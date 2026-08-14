"""Run the bounded live provider/tool-call smoke and persist atomic reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.provider_smoke import evaluate_provider_smoke, render_provider_smoke_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/stages/agent-product-live-backtest.manifest.json"),
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("docs/reports/product/agent-product-live-provider-smoke.json"),
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=Path("docs/reports/product/agent-product-live-provider-smoke.md"),
    )
    parser.add_argument(
        "--markdown-en-out",
        type=Path,
        default=Path("docs/reports/product/agent-product-live-provider-smoke.en.md"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
    report = evaluate_provider_smoke(root, manifest_path=manifest)
    _write(args.json_out, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write(args.markdown_out, render_provider_smoke_markdown(report))
    _write(args.markdown_en_out, render_provider_smoke_markdown(report, language="en"))
    return 0 if report["passed"] else 1


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
