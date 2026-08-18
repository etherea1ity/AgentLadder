#!/usr/bin/env python3
"""Dry-run for ``prepare_pretrain_corpus.py``.

Downloads only a small number of dataset samples (default 200) and writes the
normalized result to a temporary file.  This validates streaming, text
extraction, line-width limiting, token estimation, and file writing without
producing the full 2.5B-token corpus.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import prepare_pretrain_corpus as prep


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run the fineweb-edu pretraining corpus writer."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=prep.DEFAULT_CONFIG_PATH,
        help="Path to config/corpus.toml (default: repo config/corpus.toml).",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=200,
        help="Maximum number of dataset samples to download.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(tempfile.gettempdir()) / "klara_corpus_dryrun.txt",
        help="Output file for the dry-run corpus (default: system temp dir).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.samples <= 0:
        raise SystemExit("--samples must be positive")

    config = prep.CorpusConfig.from_toml(args.config)
    config.max_samples = args.samples
    config.output_path = args.output.expanduser()

    prep.run(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())