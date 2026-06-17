from __future__ import annotations

import argparse
from pathlib import Path

from agent_ladder.knowledge.paper.indexing import write_indexes


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic lightweight Chapter 3 paper indexes.")
    parser.add_argument("--root", default="data/papers")
    args = parser.parse_args()
    written = write_indexes(Path(args.root))
    for name, path in written.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
