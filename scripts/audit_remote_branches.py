"""Execute every unique remote branch in an isolated worktree and inventory architecture."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter
from typing import Any


CAPABILITIES = {
    "minimal_loop": "src/klara/core/loop.py",
    "tool_runtime": "src/klara/tools/executor.py",
    "hooks_trace": "src/klara/core/hooks.py",
    "harness_config": "src/klara/app/harness.py",
    "context_budget": "src/klara/context/controller.py",
    "provider_recovery": "src/klara/infra/llm/routed_client.py",
    "skills_runtime": "src/klara/skills/controller.py",
    "long_term_memory": "src/klara/memory/service.py",
    "permission_engine": "src/klara/permissions/service.py",
    "durable_tasks": "src/klara/tasks/service.py",
    "background_scheduler": "src/klara/scheduler/service.py",
    "subagent_team_worktree": "src/klara/teams/service.py",
    "mcp": "src/klara/mcp/service.py",
    "production_queue": "src/klara/production/repository.py",
    "behavior_eval": "src/klara/eval/behavior_runtime.py",
    "external_benchmarks": "src/klara/eval/public_memory_live.py",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    audit_root = (root / ".tmp" / "branch-audit-worktrees").resolve()
    if root not in audit_root.parents:
        raise ValueError("branch_audit_path_outside_repository")
    audit_root.mkdir(parents=True, exist_ok=True)
    cache_root = (root / ".tmp" / "branch-audit-cache").resolve()
    if root not in cache_root.parents:
        raise ValueError("branch_audit_cache_outside_repository")
    cache_root.mkdir(parents=True, exist_ok=True)
    refs = _remote_refs(root)
    commits: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for index, (branch, commit) in enumerate(refs, start=1):
        if commit not in commits:
            cache_path = cache_root / f"{commit}.json"
            if cache_path.is_file():
                commits[commit] = json.loads(cache_path.read_text(encoding="utf-8"))
                print(f"[{index}/{len(refs)}] reuse {branch} {commit[:12]}", flush=True)
                result = commits[commit]
            else:
                worktree = (audit_root / f"{index:02d}-{commit[:12]}").resolve()
                if audit_root not in worktree.parents:
                    raise ValueError("branch_worktree_outside_audit_root")
                print(f"[{index}/{len(refs)}] execute {branch} {commit[:12]}", flush=True)
                commits[commit] = _execute_commit(
                    root,
                    worktree=worktree,
                    commit=commit,
                    timeout_seconds=args.timeout_seconds,
                )
                cache_path.write_text(
                    json.dumps(commits[commit], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                    newline="\n",
                )
        result = commits[commit]
        rows.append(
            {
                "branch": branch,
                "commit": commit,
                "shared_commit_branches": [
                    name for name, candidate in refs if candidate == commit
                ],
                **result,
            }
        )
    report = {
        "schema_version": "klara.remote-branch-architecture-audit.v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "remote": _run(root, ["git", "remote", "get-url", "origin"])["stdout"].strip(),
        "branch_count": len(rows),
        "unique_commit_count": len(commits),
        "execution_policy": {
            "checkout": "detached isolated git worktree per unique commit",
            "commands": [
                f"{sys.executable} -m compileall -q src apps",
                f"{sys.executable} -m pytest -q",
            ],
            "live_provider_calls": False,
            "interpretation": (
                "This proves each historical commit executes its own local suite. "
                "It does not prove current production architecture or live-provider quality."
            ),
        },
        "summary": {
            "compile_passed": sum(row["compile"]["passed"] for row in rows),
            "pytest_passed": sum(row["pytest"]["passed"] for row in rows),
            "architecturally_complete": sum(
                row["architecture"]["hard_requirements_passed"] for row in rows
            ),
        },
        "branches": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return 0


def _remote_refs(root: Path) -> list[tuple[str, str]]:
    result = _run(
        root,
        [
            "git",
            "for-each-ref",
            "--format=%(refname:short)|%(objectname)",
            "refs/remotes/origin",
        ],
    )
    refs = []
    for line in result["stdout"].splitlines():
        branch, separator, commit = line.partition("|")
        if not separator or branch in {"origin", "origin/HEAD"}:
            continue
        refs.append((branch, commit))
    return sorted(refs)


def _execute_commit(
    root: Path,
    *,
    worktree: Path,
    commit: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    _run(root, ["git", "worktree", "add", "--detach", str(worktree), commit])
    try:
        compile_result = _run(
            worktree,
            [sys.executable, "-m", "compileall", "-q", "src", "apps"],
            timeout=timeout_seconds,
            check=False,
        )
        pytest_result = _run(
            worktree,
            [sys.executable, "-m", "pytest", "-q"],
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "tree_file_count": _tree_file_count(root, commit),
            "compile": _public_command(compile_result),
            "pytest": _public_command(pytest_result),
            "architecture": _architecture_inventory(worktree),
        }
    finally:
        removal = _run(
            root,
            ["git", "worktree", "remove", "--force", str(worktree)],
            check=False,
        )
        if removal["returncode"] != 0:
            print(f"worktree cleanup failed: {worktree}", flush=True)


def _architecture_inventory(worktree: Path) -> dict[str, Any]:
    capabilities = {
        name: (worktree / relative).is_file()
        for name, relative in CAPABILITIES.items()
    }
    loop = _read(worktree / "src/klara/core/loop.py")
    run_service = _read(worktree / "apps/api/services/run_service.py")
    memory_repository = _read(worktree / "src/klara/memory/repository.py")
    memory_retrieval = _read(worktree / "src/klara/memory/retrieval.py")
    hard = {
        "step_checkpoint_and_resume": bool(
            re.search(r"checkpoint", loop, re.IGNORECASE)
            and re.search(r"resume", loop, re.IGNORECASE)
        ),
        "ordinary_runs_not_daemon_thread_only": not (
            "threading.Thread" in run_service and "daemon=True" in run_service
        ) if run_service else False,
        "memory_primary_key_is_owner_namespaced": bool(
            re.search(
                r"PRIMARY KEY\s*\(\s*tenant_id\s*,\s*user_id\s*,\s*memory_id\s*\)",
                memory_repository,
                re.IGNORECASE,
            )
        ),
        "memory_has_learned_embedding_boundary": any(
            marker in memory_retrieval
            for marker in ("Embedding", "embedder", "embedding_model", "VectorIndex")
        ),
        "memory_has_formation_pipeline": (worktree / "src/klara/memory/formation.py").is_file(),
        "production_queue_present": capabilities["production_queue"],
        "permission_engine_present": capabilities["permission_engine"],
    }
    return {
        "capabilities": capabilities,
        "hard_requirements": hard,
        "hard_requirements_passed": all(hard.values()),
    }


def _tree_file_count(root: Path, commit: str) -> int:
    result = _run(root, ["git", "ls-tree", "-r", "--name-only", commit])
    return len(result["stdout"].splitlines())


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _run(
    cwd: Path,
    command: list[str],
    *,
    timeout: int = 60,
    check: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    env = dict(os.environ)
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "command": command,
            "returncode": 124,
            "stdout": stdout,
            "stderr": f"{stderr}\ncommand_timed_out_after_{timeout}_seconds".strip(),
            "duration_ms": int((perf_counter() - started) * 1000),
        }
    result = {
        "command": command,
        "returncode": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "duration_ms": int((perf_counter() - started) * 1000),
    }
    if check and process.returncode != 0:
        raise RuntimeError(
            f"command_failed:{process.returncode}:{' '.join(command)}\n"
            f"{process.stdout[-2000:]}\n{process.stderr[-2000:]}"
        )
    return result


def _public_command(result: dict[str, Any]) -> dict[str, Any]:
    output = f"{result['stdout']}\n{result['stderr']}".strip()
    summary_lines = [line for line in output.splitlines() if line.strip()][-8:]
    return {
        "passed": result["returncode"] == 0,
        "returncode": result["returncode"],
        "duration_ms": result["duration_ms"],
        "summary": "\n".join(summary_lines),
    }


if __name__ == "__main__":
    raise SystemExit(main())
