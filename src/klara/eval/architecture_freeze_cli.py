from __future__ import annotations

import argparse
import json
from pathlib import Path

from klara.eval.architecture_freeze import build_architecture_freeze_report, render_architecture_freeze


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--gate-root", type=Path, required=True)
    parser.add_argument("--branch-audit", type=Path, required=True)
    parser.add_argument("--python-tests", type=int, required=True)
    parser.add_argument("--python-skips", type=int, default=0)
    parser.add_argument("--web-test-files", type=int, required=True)
    parser.add_argument("--web-tests", type=int, required=True)
    parser.add_argument("--web-build-passed", action="store_true")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument("--markdown-en-out", type=Path, required=True)
    args = parser.parse_args()
    report = build_architecture_freeze_report(
        args.repository_root.resolve(),
        args.gate_root.resolve(),
        args.branch_audit.resolve(),
        python_tests_collected=args.python_tests,
        python_tests_skipped=args.python_skips,
        web_test_files=args.web_test_files,
        web_tests=args.web_tests,
        web_build_passed=args.web_build_passed,
    )
    for path, content in (
        (args.json_out, json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
        (args.markdown_out, render_architecture_freeze(report, english=False)),
        (args.markdown_en_out, render_architecture_freeze(report, english=True)),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
