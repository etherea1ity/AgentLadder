"""Write Chapter 15 deterministic JSON and bilingual Markdown evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.chapter15 import evaluate_chapter15, render_chapter15_markdown


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument("--markdown-en-out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate_chapter15(args.repository_root.resolve())
    for path in (args.json_out, args.markdown_out, args.markdown_en_out):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    args.markdown_out.write_text(render_chapter15_markdown(report), encoding="utf-8", newline="\n")
    args.markdown_en_out.write_text(render_chapter15_markdown(report, language="en"), encoding="utf-8", newline="\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
