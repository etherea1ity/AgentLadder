"""Run the bounded two-provider smoke and write bilingual evidence artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from klara.eval.provider_smoke import (
    evaluate_provider_smoke,
    render_provider_smoke_markdown,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument("--markdown-en-out", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    report = evaluate_provider_smoke(
        root,
        manifest_path=args.manifest.resolve(),
    )
    for path in (args.json_out, args.markdown_out, args.markdown_en_out):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    args.markdown_out.write_text(
        render_provider_smoke_markdown(
            report,
            chinese_name=args.markdown_out.name,
            english_name=args.markdown_en_out.name,
        ),
        encoding="utf-8",
        newline="\n",
    )
    args.markdown_en_out.write_text(
        render_provider_smoke_markdown(
            report,
            language="en",
            chinese_name=args.markdown_out.name,
            english_name=args.markdown_en_out.name,
        ),
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "requests": report["request_count"],
                "native_costs": report["native_costs"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
