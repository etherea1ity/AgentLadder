from __future__ import annotations

import argparse
from pathlib import Path

from agent_ladder.knowledge.paper.validation import render_validation_report, validate_paper_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Chapter 3 Paper Corpus schema and file integrity.")
    parser.add_argument("--root", default="data/papers")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--paper-id", default=None, help="Accepted for compatibility; validates full corpus currently")
    parser.add_argument("--fixture", action="store_true", help="Validate fixture root instead of real corpus")
    args = parser.parse_args()
    root = Path("data/papers/fixtures") if args.fixture else Path(args.root)
    report = validate_paper_corpus(root, strict=args.strict)
    out = root / "quality_reports" / "validation_report.md" if root.name != "fixtures" else Path("data/papers/quality_reports/fixtures_validation_report.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_validation_report(report), encoding="utf-8")
    print(f"validation_status={'passed' if report.ok else 'failed'}")
    print(f"errors={len(report.errors)} warnings={len(report.warnings)}")
    print(f"wrote {out}")
    return 1 if args.strict and not report.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
