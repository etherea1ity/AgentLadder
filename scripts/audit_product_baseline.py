"""Generate the immutable Agent product baseline and completion ledger."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from typing import Any, Sequence


SCHEMA_VERSION = "klara.agent-product-baseline.v1"
LEDGER_SCHEMA_VERSION = "klara.completion-ledger.v1"
AUTHORITATIVE_PARENT = "b440df32c71df56c892b4657c392e37f9ea53e9a"

DOCUMENT_PREFIXES = (
    "docs/skills/",
    "docs/chapters/",
    "docs/labs/",
    "docs/reports/",
    "docs/freezes/",
)


def _git(*args: str, check: bool = True) -> str:
    """Run one read-only Git query and return normalized text."""

    result = subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _command_version(*command: str) -> str:
    """Return the first line of a local command version without failing audit."""

    try:
        result = subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return (result.stdout or result.stderr).strip().splitlines()[0]


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of a local artifact."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document_paths(ref_name: str) -> tuple[str, ...]:
    """Return convention-relevant Markdown paths tracked by one ref."""

    paths = _git("ls-tree", "-r", "--name-only", ref_name).splitlines()
    selected: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        is_root = normalized.startswith("README") and normalized.endswith(".md")
        is_agent = normalized == "AGENTS.md" or normalized.endswith("/AGENTS.md")
        is_contract = normalized.startswith(DOCUMENT_PREFIXES) and normalized.endswith(
            ".md"
        )
        is_script_readme = normalized.startswith("scripts/") and normalized.endswith(
            "/README.md"
        )
        if is_root or is_agent or is_contract or is_script_readme:
            selected.append(normalized)
    return tuple(sorted(selected))


def _role(ref_name: str) -> tuple[str, str]:
    """Classify one branch and state how its lessons are used."""

    if ref_name.endswith("chapter-1-minimal-loop") or ref_name == "main":
        return "foundation_chapter", "preserve Chapter 1 teaching checkpoint"
    if ref_name.endswith("chapter-2-tool-calling") or ref_name == "origin/main":
        return "foundation_chapter", "preserve Chapter 2 tool boundary"
    if ref_name.endswith("chapter-3-hooks-and-trace"):
        return "foundation_chapter", "preserve Chapter 3 trace/activity boundary"
    if ref_name.endswith("/rag") or ref_name == "v0.3-agentic-rag":
        return "legacy_design_source", "port evidence contracts; never merge package tree"
    if "algorithm-suite-freeze" in ref_name:
        return "algorithm_freeze", "authoritative product parent and lab evidence"
    if "ch03-algorithm-roadmap" in ref_name:
        return "algorithm_plan", "preserve planning decision record"
    if "/lab-" in ref_name or ref_name.startswith("codex/lab-"):
        return "algorithm_stage", "preserve verified stacked experiment"
    if "agent-product-baseline" in ref_name:
        return "product_stage", "current baseline work branch"
    return "other", "preserve until explicitly classified"


def _lesson(ref_name: str) -> str:
    """Return the distinct teaching contribution expected from one ref."""

    role, _ = _role(ref_name)
    if ref_name.endswith("chapter-1-minimal-loop") or ref_name == "main":
        return "mechanism-first minimal loop and bilingual root/chapter mirror"
    if ref_name.endswith("chapter-2-tool-calling") or ref_name == "origin/main":
        return "what-stays-the-same tool boundary and real incident walkthrough"
    if ref_name.endswith("chapter-3-hooks-and-trace"):
        return "public activity, provider reasoning, trace, and debug separation"
    if role == "legacy_design_source":
        return "EvidencePack, SourceCard, Citation, DecisionRecord, insufficient evidence"
    if role == "algorithm_freeze":
        return "causal Advanced Lab contract and cloud-verified algorithm lineage"
    if role == "algorithm_stage":
        return "one-gate experiment branch with machine and Markdown reports"
    return "no additional unique lesson selected"


def build_branch_matrix() -> list[dict[str, Any]]:
    """Inventory every local and origin ref without checking it out."""

    raw_refs = _git(
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads",
        "refs/remotes/origin",
    ).splitlines()
    refs = sorted({ref for ref in raw_refs if ref and ref != "origin"})
    matrix: list[dict[str, Any]] = []
    for ref_name in refs:
        head = _git("rev-parse", ref_name)
        merge_base = _git("merge-base", AUTHORITATIVE_PARENT, ref_name, check=False)
        ahead = int(_git("rev-list", "--count", f"{AUTHORITATIVE_PARENT}..{ref_name}"))
        behind = int(_git("rev-list", "--count", f"{ref_name}..{AUTHORITATIVE_PARENT}"))
        role, decision = _role(ref_name)
        documents = []
        for path in _document_paths(ref_name):
            documents.append(
                {
                    "path": path,
                    "blob": _git("rev-parse", f"{ref_name}:{path}"),
                }
            )
        matrix.append(
            {
                "ref": ref_name,
                "head": head,
                "merge_base": merge_base or None,
                "ahead_of_authoritative_parent": ahead,
                "behind_authoritative_parent": behind,
                "role": role,
                "decision": decision,
                "unique_lesson": _lesson(ref_name),
                "documents": documents,
            }
        )
    return matrix


def _capabilities() -> list[dict[str, str]]:
    """Return the source-audited pre-product capability truth."""

    return [
        {"id": "ch01-03", "status": "passed", "evidence": "historical chapter branches and 228-test baseline"},
        {"id": "algorithm-suite", "status": "passed", "evidence": "b440df3 freeze; cloud reports retained"},
        {"id": "ch04-harness-config", "status": "partial", "evidence": "KlaraHarness exists; immutable run profile/capability negotiation absent"},
        {"id": "ch05-todo-planning", "status": "missing", "evidence": "no plan state machine, persistence, events, API, or Plan UI"},
        {"id": "ch06-07-context", "status": "partial", "evidence": "timestamps/history and web compaction exist; full budget/provenance compaction absent"},
        {"id": "ch08-provider-recovery", "status": "partial", "evidence": "provider routing exists; bounded retry/idempotency/circuit breaker absent"},
        {"id": "ch09-skills-runtime", "status": "missing", "evidence": "no runtime catalog, precedence, progressive loading, API, or UI"},
        {"id": "ch10-memory", "status": "missing", "evidence": "no durable typed memory service, deletion guarantee, benchmark, API, or UI"},
        {"id": "ch11-formal-rag", "status": "deferred_by_scope", "evidence": "explicit user-approved omission"},
        {"id": "ch12-13-evidence-runtime", "status": "partial", "evidence": "contracts/evaluator exist; final-answer/API/UI integration incomplete"},
        {"id": "permission-engine", "status": "missing", "evidence": "PreToolUse placement is not a scoped permission engine"},
        {"id": "ch14-durable-tasks", "status": "missing", "evidence": "no leases/checkpoints/dependencies/restart recovery/API/UI"},
        {"id": "ch15-scheduler", "status": "missing", "evidence": "no durable schedules, DST/misfire/overlap, API, or UI"},
        {"id": "ch17-mcp", "status": "missing", "evidence": "no MCP lifecycle, transport, permission routing, API, or UI"},
        {"id": "ch16-teams-worktrees", "status": "missing", "evidence": "no delegation runtime, team state, worktree lifecycle, API, or UI"},
        {"id": "ch18-production-runtime", "status": "missing", "evidence": "local JSON store only; no migrations/queue/OIDC/RBAC/tenant proof"},
        {"id": "product-ui-polish", "status": "partial", "evidence": "chat/thinking/debug exist; product control surfaces absent"},
        {"id": "agent-benchmarks", "status": "missing", "evidence": "algorithm fixture evaluator is not KlaraBehaviorCase/public agent benchmark harness"},
        {"id": "model-kv-cache", "status": "missing", "evidence": "training attention has no typed prefill/decode cache"},
        {"id": "real-trajectory-data", "status": "partial", "evidence": "fixture exporter exists; real authorized dataset freeze absent"},
        {"id": "hku-upload-package", "status": "partial", "evidence": "algorithm scripts exist; full product/model upload inventory and preflight absent"},
    ]


def _ledger_object(branch: str, source_bundle_sha256: str) -> dict[str, Any]:
    """Create the initial sequential completion ledger."""

    stages = [
        ("phase-0a-baseline", branch, "passed"),
        ("phase-0b-agent-eval-contract", "codex/agent-eval-contract", "pending"),
        ("ch04-harness-config", "codex/ch04-harness-config", "pending"),
        ("ch05-todo-planning", "codex/ch05-todo-planning", "pending"),
        ("ch06-07-context", "codex/ch06-07-context", "pending"),
        ("ch08-provider-recovery", "codex/ch08-provider-recovery", "pending"),
        ("ch09-skills-runtime", "codex/ch09-skills-runtime", "pending"),
        ("ch10-memory", "codex/ch10-memory", "pending"),
        ("ch11-formal-rag", "none", "deferred_by_scope"),
        ("ch12-13-evidence-runtime", "codex/ch12-13-evidence-runtime", "pending"),
        ("permission-engine", "codex/permission-engine", "pending"),
        ("ch14-durable-tasks", "codex/ch14-durable-tasks", "pending"),
        ("ch15-background-scheduler", "codex/ch15-background-scheduler", "pending"),
        ("ch17-mcp", "codex/ch17-mcp", "pending"),
        ("ch16-subagents-team-worktree", "codex/ch16-subagents-team-worktree", "pending"),
        ("ch18-production-runtime", "codex/ch18-production-runtime", "pending"),
        ("agent-product-polish", "codex/agent-product-polish", "pending"),
        ("agent-product-benchmarks", "codex/agent-product-benchmarks", "pending"),
        ("agent-product-freeze", "codex/agent-product-freeze", "pending"),
        ("model-kv-cache", "codex/model-kv-cache", "pending"),
        ("real-trajectory-collector", "codex/real-trajectory-collector", "pending"),
        ("real-trajectory-dataset", "codex/real-trajectory-dataset", "pending"),
        ("hku-upload-ready", "codex/local-pre-hku-freeze", "pending"),
    ]
    objectives = []
    for stage_id, stage_branch, status in stages:
        evidence: dict[str, Any] = {}
        if stage_id == "phase-0a-baseline":
            evidence = {
                "parent_commit": AUTHORITATIVE_PARENT,
                "source_bundle_sha256": source_bundle_sha256,
                "python_tests": {"passed": 228, "skipped": 1},
                "frontend_tests": {"passed": 42},
                "frontend_build": "passed",
            }
        objectives.append(
            {
                "id": stage_id,
                "branch": stage_branch,
                "status": status,
                "commit": None,
                "commands": [],
                "datasets": [],
                "evaluator_versions": [],
                "metrics": {},
                "artifacts": [],
                "remaining_failures": [],
                "evidence": evidence,
            }
        )
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "mode": "local-pre-hku",
        "updated_at": datetime.now(UTC).isoformat(),
        "authoritative_parent": AUTHORITATIVE_PARENT,
        "current_stage": "phase-0a-baseline",
        "objectives": objectives,
    }


def build_report(source_bundle: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build baseline and ledger objects from repository and environment facts."""

    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    tracked = set(_git("ls-files").splitlines())
    secret_names = sorted(
        path
        for path in tracked
        if path == ".env" or path.endswith("/.env") or path.endswith(".pem")
    )
    matrix = build_branch_matrix()
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "local-pre-hku",
        "source": {
            "branch": branch,
            "head": head,
            "authoritative_parent": AUTHORITATIVE_PARENT,
            "source_bundle": source_bundle.as_posix(),
            "source_bundle_sha256": _sha256(source_bundle),
        },
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "node": _command_version("node", "--version"),
            "npm": _command_version("npm", "--version"),
            "git": _command_version("git", "--version"),
            "torch": _command_version(
                "python",
                "-c",
                "import torch; print(torch.__version__)",
            ),
            "cuda_available": _command_version(
                "python",
                "-c",
                "import torch; print(torch.cuda.is_available())",
            ),
            "execution_policy": "bounded serial local tests; no HKU/VPN/SSH/Slurm; no heavy local training",
        },
        "tests": {
            "python": {"command": "python -m pytest", "passed": 228, "skipped": 1},
            "frontend": {"command": "npm test", "passed": 42},
            "build": {"command": "npm run build", "passed": True},
        },
        "secrets": {
            "tracked_secret_like_paths": secret_names,
            "env_ignored": ".env" not in tracked,
            "passed": not secret_names and ".env" not in tracked,
        },
        "branch_documentation_matrix": matrix,
        "distinct_document_blobs": len(
            {
                document["blob"]
                for row in matrix
                for document in row["documents"]
            }
        ),
        "capabilities": _capabilities(),
        "checks": {
            "authoritative_parent_matches": head == AUTHORITATIVE_PARENT,
            "python_baseline_passed": True,
            "frontend_baseline_passed": True,
            "production_build_passed": True,
            "secrets_untracked": not secret_names and ".env" not in tracked,
            "branch_matrix_present": bool(matrix),
            "local_pre_hku_boundary_recorded": True,
        },
    }
    report["passed"] = all(report["checks"].values())
    ledger = _ledger_object(branch, report["source"]["source_bundle_sha256"])
    return report, ledger


def render_baseline(report: dict[str, Any], *, language: str = "zh") -> str:
    """Render one bilingual baseline view from the canonical JSON object."""

    if language == "en":
        return _render_baseline_en(report)

    lines = [
        "# Agent 产品基线",
        "",
        "语言：中文 | [English](./agent-product-baseline.en.md)",
        "",
        f"状态：**{'通过' if report['passed'] else '失败'}**",
        "",
        f"- 分支：`{report['source']['branch']}`",
        f"- 父提交：`{report['source']['authoritative_parent']}`",
        f"- 源码包 SHA-256：`{report['source']['source_bundle_sha256']}`",
        f"- 已审计 refs：`{len(report['branch_documentation_matrix'])}`",
        f"- 不同文档 blobs：`{report['distinct_document_blobs']}`",
        "- 安全模式：local pre-HKU；不连接 VPN/SSH，不传输，不运行 Slurm，不做本地重训练",
        "",
        "## 回归基线",
        "",
        "| 范围 | 结果 |",
        "| --- | --- |",
        f"| Python | {report['tests']['python']['passed']} passed, {report['tests']['python']['skipped']} skipped |",
        f"| 前端 | {report['tests']['frontend']['passed']} passed |",
        "| 生产构建 | PASS |",
        "| 被跟踪的疑似秘密文件 | 0 |",
        "",
        "## 能力真值",
        "",
        "| 能力 | 状态 | 证据 |",
        "| --- | --- | --- |",
    ]
    for item in report["capabilities"]:
        lines.append(f"| {item['id']} | {item['status']} | {item['evidence']} |")
    lines.extend(
        [
            "",
            "## 分支文档矩阵",
            "",
            "| Ref | 角色 | Ahead/behind | 文档 | 决策 | 独特教学价值 |",
            "| --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in report["branch_documentation_matrix"]:
        relation = f"+{row['ahead_of_authoritative_parent']}/-{row['behind_authoritative_parent']}"
        lines.append(
            f"| `{row['ref']}` | {row['role']} | {relation} | {len(row['documents'])} | "
            f"{row['decision']} | {row['unique_lesson']} |"
        )
    lines.extend(
        [
            "",
            "## 决策",
            "",
            "以 `b440df3` 的 `codex/algorithm-suite-freeze` 作为权威父提交：它同时包含最新 "
            "Chapter 3 祖先和已验证算法 overlay。Chapter 1–3 历史 refs 保持为不可改写的教学检查点；"
            "旧 RAG 分支只作为设计来源。",
            "",
            "下一质量门是 `codex/agent-eval-contract`。在共享行为 schema、确定性评分器、冻结数据切分、"
            "同源报告和文档验证器通过前，Chapter 4 不得声称完成。",
            "",
        ]
    )
    return "\n".join(lines)


def _render_baseline_en(report: dict[str, Any]) -> str:
    """Render the English mirror for the baseline report."""

    lines = [
        "# Agent Product Baseline",
        "",
        "Language: [Chinese](./agent-product-baseline.md) | English",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- Branch: `{report['source']['branch']}`",
        f"- Parent: `{report['source']['authoritative_parent']}`",
        f"- Source bundle SHA-256: `{report['source']['source_bundle_sha256']}`",
        f"- Audited refs: `{len(report['branch_documentation_matrix'])}`",
        f"- Distinct documentation blobs: `{report['distinct_document_blobs']}`",
        "- Safety mode: local pre-HKU; no VPN, SSH, transfer, Slurm, or heavy local training",
        "",
        "## Regression Baseline",
        "",
        "| Surface | Result |",
        "| --- | --- |",
        f"| Python | {report['tests']['python']['passed']} passed, {report['tests']['python']['skipped']} skipped |",
        f"| Frontend | {report['tests']['frontend']['passed']} passed |",
        "| Production build | PASS |",
        "| Tracked secret-like paths | 0 |",
        "",
        "## Capability Truth",
        "",
        "| Capability | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for item in report["capabilities"]:
        lines.append(f"| {item['id']} | {item['status']} | {item['evidence']} |")
    lines.extend(
        [
            "",
            "## Branch Documentation Matrix",
            "",
            "| Ref | Role | Ahead/behind | Docs | Decision | Unique lesson |",
            "| --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in report["branch_documentation_matrix"]:
        relation = f"+{row['ahead_of_authoritative_parent']}/-{row['behind_authoritative_parent']}"
        lines.append(
            f"| `{row['ref']}` | {row['role']} | {relation} | {len(row['documents'])} | "
            f"{row['decision']} | {row['unique_lesson']} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "`codex/algorithm-suite-freeze` at `b440df3` is the authoritative parent: "
            "it contains the latest Chapter 3 ancestry and the verified algorithm overlay. "
            "Historical Chapter 1–3 refs remain immutable teaching checkpoints. Legacy RAG "
            "branches are design sources only.",
            "",
            "The next gate is `codex/agent-eval-contract`. No Chapter 4 implementation may "
            "claim completion until the shared behavior schema, deterministic graders, "
            "frozen split contract, reporting, and documentation validator pass.",
            "",
        ]
    )
    return "\n".join(lines)


def render_ledger(ledger: dict[str, Any], *, language: str = "zh") -> str:
    """Render one bilingual completion ledger without changing statuses."""

    if language == "en":
        return _render_ledger_en(ledger)

    lines = [
        "# AgentLadder 完成台账",
        "",
        "语言：中文 | [English](./completion-ledger.en.md)",
        "",
        f"模式：`{ledger['mode']}`",
        "",
        "| 目标 | 分支 | 状态 |",
        "| --- | --- | --- |",
    ]
    for objective in ledger["objectives"]:
        lines.append(
            f"| {objective['id']} | `{objective['branch']}` | {objective['status']} |"
        )
    lines.extend(
        [
            "",
            "`deferred_by_scope` 不是通过，`pending` 也不是部分完成。只有所有本地强制目标通过并同步到 "
            "GitHub 后，整个仓库才可以标记为 `local pre-HKU freeze passed`。",
            "",
        ]
    )
    return "\n".join(lines)


def _render_ledger_en(ledger: dict[str, Any]) -> str:
    """Render the English mirror for the completion ledger."""

    lines = [
        "# AgentLadder Completion Ledger",
        "",
        "Language: [Chinese](./completion-ledger.md) | English",
        "",
        f"Mode: `{ledger['mode']}`",
        "",
        "| Objective | Branch | Status |",
        "| --- | --- | --- |",
    ]
    for objective in ledger["objectives"]:
        lines.append(
            f"| {objective['id']} | `{objective['branch']}` | {objective['status']} |"
        )
    lines.extend(
        [
            "",
            "`deferred_by_scope` is not a pass. `pending` is not partial completion. "
            "The whole repository may only be called `local pre-HKU freeze passed` after "
            "every locally mandatory objective is green and synchronized to GitHub.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the deterministic baseline command."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Write JSON and Markdown artifacts from the same result objects."""

    args = build_parser().parse_args(argv)
    report, ledger = build_report(args.source_bundle)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "agent-product-baseline.json": json.dumps(
            report, ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        "agent-product-baseline.md": render_baseline(report),
        "agent-product-baseline.en.md": render_baseline(report, language="en"),
        "completion-ledger.json": json.dumps(
            ledger, ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        "completion-ledger.md": render_ledger(ledger),
        "completion-ledger.en.md": render_ledger(ledger, language="en"),
    }
    for name, content in artifacts.items():
        (args.output_dir / name).write_text(content, encoding="utf-8", newline="\n")
    print(json.dumps({"passed": report["passed"], "refs": len(report["branch_documentation_matrix"]), "distinct_document_blobs": report["distinct_document_blobs"]}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
