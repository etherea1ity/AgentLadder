from __future__ import annotations

import argparse
from pathlib import Path

from agent_ladder.knowledge.paper.migration import (
    corpus_statistics,
    normalize_existing_corpus,
    render_corpus_report,
    render_migration_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize/migrate existing local paper files into the Chapter 3 Paper Corpus schema.")
    parser.add_argument("--input", default="data/papers/论文", help="Source drop/staging path. Originals are never deleted.")
    parser.add_argument("--root", default="data/papers", help="Paper corpus root")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--paper-id", default=None)
    parser.add_argument("--mode", choices=["audit_only", "migrate_existing", "rebuild_processed"], default="migrate_existing")
    parser.add_argument("--overwrite", action="store_true", help="Reserved for rebuild mode; default is false")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    reports = root / "quality_reports"
    reports.mkdir(parents=True, exist_ok=True)
    if args.mode == "audit_only":
        print("audit_only selected; no migration performed")
        return 0
    migration = normalize_existing_corpus(
        root,
        input_path=Path(args.input),
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        limit=args.limit,
        paper_id=args.paper_id,
    )
    (reports / "migration_report.md").write_text(render_migration_report(migration), encoding="utf-8")
    if not args.dry_run:
        stats = corpus_statistics(root)
        (reports / "corpus_report.md").write_text(render_corpus_report(stats), encoding="utf-8")
    print(f"migrated={migration['migrated_paper_count']} dry_run={args.dry_run}")
    print(f"wrote {reports / 'migration_report.md'}")
    if not args.dry_run:
        print(f"wrote {reports / 'corpus_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
