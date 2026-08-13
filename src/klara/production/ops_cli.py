"""Offline integrity, backup, restore, and retention operations for Klara SQLite."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Sequence

from klara.production.repository import ProductionRepository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("integrity")
    backup = subcommands.add_parser("backup")
    backup.add_argument("--output", type=Path, required=True)
    restore = subcommands.add_parser("restore")
    restore.add_argument("--input", type=Path, required=True)
    retention = subcommands.add_parser("retention")
    retention.add_argument("--older-than-days", type=int, required=True)
    args = parser.parse_args(argv)
    repository = ProductionRepository(args.database)
    if args.command == "integrity":
        report = repository.integrity_report()
    elif args.command == "backup":
        report = repository.backup_to(args.output)
    elif args.command == "restore":
        report = repository.restore_from(args.input)
    else:
        if not 1 <= args.older_than_days <= 3650:
            parser.error("--older-than-days must be between 1 and 3650")
        cutoff = datetime.now(UTC) - timedelta(days=args.older_than_days)
        report = {
            "schema_version": "klara.production-retention.v1",
            "cutoff": cutoff.isoformat(),
            "counts": repository.apply_retention(before_epoch=cutoff.timestamp()),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
