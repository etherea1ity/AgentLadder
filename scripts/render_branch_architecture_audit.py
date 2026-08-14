"""Render a compact bilingual report from the isolated remote-branch audit."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path


SOURCES = {
    "OpenAI Agents SDK": "https://openai.github.io/openai-agents-python/",
    "LangGraph persistence": "https://docs.langchain.com/oss/python/langgraph/persistence",
    "LangGraph functional API": "https://docs.langchain.com/oss/python/langgraph/functional-api",
    "AutoGen state": "https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/tutorial/state.html",
    "Mem0": "https://github.com/mem0ai/mem0",
    "OpenHands architecture": "https://github.com/OpenHands/OpenHands/blob/main/docs/architecture.md",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--zh-output", type=Path, required=True)
    parser.add_argument("--en-output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    branches = [_sanitize(row) for row in raw["branches"]]
    report = {
        "schema_version": "klara.remote-branch-architecture-report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_audit_evaluated_at": raw["evaluated_at"],
        "remote": raw["remote"],
        "branch_count": raw["branch_count"],
        "unique_commit_count": raw["unique_commit_count"],
        "summary": raw["summary"],
        "interpretation": {
            "historical_snapshot": True,
            "live_provider_calls": False,
            "latest_branch_live_gate_required_separately": True,
            "architecturally_complete_means_all_static_hard_requirements_present": True,
        },
        "reference_architectures": SOURCES,
        "branches": branches,
    }
    _write(args.json_output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _write(args.zh_output, _markdown(report, chinese=True))
    _write(args.en_output, _markdown(report, chinese=False))
    return 0


def _sanitize(row: dict[str, object]) -> dict[str, object]:
    pytest = dict(row["pytest"])
    architecture = dict(row["architecture"])
    return {
        "branch": row["branch"],
        "commit": row["commit"],
        "shared_commit_branches": row["shared_commit_branches"],
        "tree_file_count": row["tree_file_count"],
        "compile": {
            "passed": dict(row["compile"])["passed"],
            "duration_ms": dict(row["compile"])["duration_ms"],
        },
        "pytest": {
            "passed": pytest["passed"],
            "duration_ms": pytest["duration_ms"],
            "failure_summary": pytest["summary"] if not pytest["passed"] else "",
        },
        "architecture": architecture,
    }


def _markdown(report: dict[str, object], *, chinese: bool) -> str:
    summary = dict(report["summary"])
    title = "远程分支架构与执行审计" if chinese else "Remote Branch Architecture and Execution Audit"
    lines = [
        f"# {title}",
        "",
        (
            "语言：中文 | [English](./remote-branch-architecture-audit.en.md)"
            if chinese
            else "Language: [Chinese](./remote-branch-architecture-audit.md) | English"
        ),
        "",
    ]
    if chinese:
        lines += [
            f"审计了 {report['branch_count']} 个远程分支（{report['unique_commit_count']} 个唯一提交）。每个唯一提交均在隔离 detached worktree 中执行 `compileall` 和完整 `pytest`。",
            "",
            f"- 编译通过：{summary['compile_passed']}/{report['branch_count']}",
            f"- 原分支测试通过：{summary['pytest_passed']}/{report['branch_count']}",
            f"- 同时满足当前静态架构硬门：{summary['architecturally_complete']}/{report['branch_count']}",
            "",
            "`origin/rag` 是唯一测试失败分支；它是独立旧路线，失败集中在真实 Agentic RAG API、运行时、可视资产、SSE 生命周期和语料校验。其余分支是逐章演进快照，测试通过不等于最终产品架构完整。正式 DeepSeek 回放只对修复后的最新可靠分支执行，不能把历史单测当成真实模型成绩。",
            "",
        ]
    else:
        lines += [
            f"Audited {report['branch_count']} remote branches ({report['unique_commit_count']} unique commits). Every unique commit ran `compileall` and its full `pytest` suite in an isolated detached worktree.",
            "",
            f"- Compile passed: {summary['compile_passed']}/{report['branch_count']}",
            f"- Historical branch tests passed: {summary['pytest_passed']}/{report['branch_count']}",
            f"- All current static architecture gates present: {summary['architecturally_complete']}/{report['branch_count']}",
            "",
            "`origin/rag` is the only failing branch. It is an independent legacy line whose failures cover the real Agentic RAG API/runtime, visual assets, SSE lifecycle, and corpus validation. The other branches are incremental chapter snapshots; passing their own tests does not make them final-product complete. Live DeepSeek replay belongs only to the repaired latest reliable branch and must not be conflated with historical unit-test evidence.",
            "",
        ]
    lines += [
        "| Branch | Commit | Compile | Tests | Current hard gates |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in report["branches"]:
        architecture = dict(row["architecture"])
        lines.append(
            f"| `{row['branch']}` | `{str(row['commit'])[:12]}` | "
            f"{'PASS' if dict(row['compile'])['passed'] else 'FAIL'} | "
            f"{'PASS' if dict(row['pytest'])['passed'] else 'FAIL'} | "
            f"{'PASS' if architecture['hard_requirements_passed'] else 'INCOMPLETE'} |"
        )
    lines += ["", "## References" if not chinese else "## 架构参照", ""]
    for name, url in SOURCES.items():
        lines.append(f"- [{name}]({url})")
    lines += [
        "",
        ("注：本报告不包含凭据、环境变量值或完整命令输出。" if chinese else "Note: this report contains no credentials, environment values, or full command output."),
        "",
    ]
    return "\n".join(lines)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
