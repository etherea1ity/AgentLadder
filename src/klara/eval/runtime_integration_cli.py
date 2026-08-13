"""Write deterministic main-Agent runtime-integration evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.runtime_integration import evaluate_runtime_integration, render_runtime_integration_markdown


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument("--markdown-en-out", type=Path, required=True)
    args = parser.parse_args(argv)
    # Placeholder reports make the bilingual-file check explicit on first run.
    for path in (args.markdown_out, args.markdown_en_out):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("runtime integration report pending\n", encoding="utf-8")
    report = evaluate_runtime_integration(args.repository_root.resolve())
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    args.markdown_out.write_text(render_runtime_integration_markdown(report), encoding="utf-8", newline="\n")
    args.markdown_en_out.write_text(render_runtime_integration_markdown(report, language="en"), encoding="utf-8", newline="\n")
    print(json.dumps({"stage": report["stage"], "passed": report["passed"], **report["metrics"]}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
