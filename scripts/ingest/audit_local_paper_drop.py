from __future__ import annotations

import argparse
from pathlib import Path

from agent_ladder.knowledge.paper.migration import audit_source_drop, render_source_audit_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a local paper source-drop without modifying files.")
    parser.add_argument("--input", required=True, help="Source drop path, e.g. data/papers/论文")
    parser.add_argument("--output", default="data/papers/quality_reports/source_audit_report.md")
    args = parser.parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    json_path = output_path.with_suffix(".json")
    if output_path.name == "source_audit_report.md":
        json_path = output_path.parent / "source_audit.json"
    audit = audit_source_drop(input_path, json_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_source_audit_report(audit), encoding="utf-8")
    print(f"wrote {output_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
