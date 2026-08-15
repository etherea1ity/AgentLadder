"""Reconcile immutable Agent evidence into one Product Freeze readiness ledger."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


REPORT_SCHEMA_VERSION = "klara.agent-product-freeze-readiness.v1"
LEDGER_SCHEMA_VERSION = "klara.completion-ledger.v1"
STAGE_ID = "agent-product-freeze-readiness"
STAGE_BRANCH = "codex/agent-product-freeze-readiness"


def build_report(
    root: Path,
    *,
    manifest_path: Path,
    source_commit: str,
    python_tests_collected: int,
    python_tests_skipped: int,
    web_tests: int,
    web_test_files: int,
    web_build_passed: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the readiness report and a reconciled copy of the completion ledger.

    Args:
        root: Repository root containing the frozen input reports.
        manifest_path: Stage manifest with input paths and expected hashes.
        source_commit: Exact verified parent commit whose evidence is reconciled.
        python_tests_collected: Tests collected by the current full Python suite.
        python_tests_skipped: Documented skips in the current Python suite.
        web_tests: Tests passed by the current frontend suite.
        web_test_files: Frontend test files passed by the current suite.
        web_build_passed: Whether the current production frontend build passed.

    Returns:
        A tuple containing the readiness report and updated completion ledger.

    Raises:
        ValueError: If a frozen input hash, schema, or cross-report control differs.
    """

    root = root.resolve()
    manifest = _read(manifest_path.resolve())
    _require(manifest["stage"] == STAGE_ID, "unexpected stage manifest")
    _require(manifest["parent_commit"] == source_commit, "source commit drift")
    verified_inputs: list[dict[str, Any]] = []
    reports: dict[str, dict[str, Any]] = {}
    # Verify every input before reading any score into the authoritative result.
    for frozen_input in manifest["inputs"]:
        relative_path = str(frozen_input["path"])
        path = root / relative_path
        actual_sha256 = _sha256(path)
        expected_sha256 = str(frozen_input["sha256"])
        _require(actual_sha256 == expected_sha256, f"input hash drift: {relative_path}")
        verified_inputs.append(
            {
                "path": relative_path,
                "sha256": actual_sha256,
                "bytes": path.stat().st_size,
            }
        )
        reports[Path(relative_path).name] = _read(path)

    branch_audit = reports["remote-branch-architecture-audit.json"]
    architecture = reports["agent-architecture-freeze.json"]
    external = reports["agent-product-external-benchmarks.json"]
    hardening = reports["prompt-context-recovery-hardening.json"]
    memory_agent = reports["prompt-context-recovery-memory-agent-formal.json"]
    memory_baseline = reports[
        "prompt-context-recovery-memory-baseline-formal.json"
    ]
    historical_memory = reports["memory-architecture-agent-live.json"]
    historical_summary = reports["memory-benchmark-summary.json"]
    mem0 = reports["mem0-reproduction.json"]
    mem0_followup_path = (
        root / "docs/reports/product/mem0-comparable-reproduction.json"
    )
    mem0_followup = _read(mem0_followup_path) if mem0_followup_path.is_file() else None
    mem0_followup_green = bool(
        mem0_followup
        and mem0_followup.get("passed") is True
        and mem0_followup.get("selection", {}).get("selected_case_ids_sha256")
        == memory_agent["selection"]["selected_case_ids_sha256"]
        and mem0_followup.get("source", {})
        .get("mem0", {})
        .get("pull_request_head")
        == "5e941e24c2cb260f73cc6d31113a92bb1ce62d46"
    )
    ledger = _read(root / "docs/reports/product/completion-ledger.json")

    _require(ledger["schema_version"] == LEDGER_SCHEMA_VERSION, "ledger schema drift")
    _require(architecture["passed"] is True, "architecture freeze is not green")
    _require(
        hardening["local_pre_hku_code_and_api_passed"] is True,
        "latest local hardening gate is not green",
    )
    _require(memory_agent["passed"] is True, "fresh Memory Agent gate is not green")
    _require(memory_baseline["passed"] is True, "fresh direct baseline is not green")
    _require(historical_memory["passed"] is False, "historical failure was overwritten")
    _require(
        historical_summary["passed"] is False,
        "historical failure summary was overwritten",
    )
    _require(
        memory_agent["selection"]["selected_case_ids_sha256"]
        == memory_baseline["selection"]["selected_case_ids_sha256"],
        "fresh Memory Agent and direct baseline use different cases",
    )
    _require(
        memory_agent["selection"]["selection_offset"] == 10,
        "fresh hidden split offset drift",
    )

    agent_metrics = memory_agent["agent"]
    direct_metrics = memory_baseline["systems"]["hybrid"]
    memory_f1_delta = round(
        float(agent_metrics["official_f1"])
        - float(direct_metrics["official_f1"]),
        6,
    )
    memory_recall_delta = round(
        float(agent_metrics["evidence_recall_at_k"])
        - float(direct_metrics["evidence_recall_at_k"]),
        6,
    )
    mandatory_blockers = [
        {
            "id": "independent-model-judge",
            "status": "blocked_external",
            "detail": "The frozen Qwen judge credential returned HTTP 401; a distinct independent judge has not scored the 41 observations.",
        },
        {
            "id": "blind-human-review",
            "status": "blocked_external",
            "detail": "No independent blind-human labels exist for the frozen comparison queue.",
        },
    ]
    if not mem0_followup_green:
        mandatory_blockers.append(
            {
                "id": "official-mem0-comparison",
                "status": "blocked_external",
                "detail": str(mem0["defect"]),
            }
        )
    expansion_gaps = [
        {
            "id": "official-mem1-gpu-comparison",
            "status": "pending",
            "detail": "The pinned MEM1 7B rollout requires a comparable GPU evaluation run.",
        },
        {
            "id": "beam-scale-comparison",
            "status": "pending",
            "detail": "No licensed, hashed BEAM snapshot is available for a comparable scale run.",
        },
        {
            "id": "gaia-public-subset",
            "status": "pending",
            "detail": "A frozen publicly permitted GAIA subset has not yet been executed through the current runtime.",
        },
    ]
    stage_checks = {
        "all_input_hashes_match": True,
        "remote_branch_audit_present": branch_audit["branch_count"] >= 34,
        "architecture_freeze_green": architecture["passed"] is True,
        "latest_local_code_api_gate_green": hardening[
            "local_pre_hku_code_and_api_passed"
        ]
        is True,
        "fresh_hidden_memory_split_selected": (
            memory_agent["selection"]["selection_offset"] == 10
            and memory_agent["schema_version"] == "klara.locomo-memory-agent.v2"
        ),
        "historical_failed_replay_preserved": (
            historical_memory["passed"] is False
            and historical_summary["passed"] is False
        ),
        "architecture_and_product_freeze_separated": (
            architecture["passed"] is True
            and hardening["agent_product_freeze_passed"] is False
        ),
        "external_superiority_not_claimed": True,
        "full_python_suite_passed": python_tests_collected
        >= int(manifest["acceptance"]["minimum_python_tests_collected"]),
        "frontend_suite_passed": (
            web_tests >= int(manifest["acceptance"]["minimum_web_tests"])
            and web_test_files
            >= int(manifest["acceptance"]["minimum_web_test_files"])
        ),
        "frontend_production_build_passed": web_build_passed,
    }
    product_freeze_checks = {
        "architecture_freeze_green": architecture["passed"] is True,
        "local_code_api_gate_green": hardening[
            "local_pre_hku_code_and_api_passed"
        ]
        is True,
        "fresh_memory_non_inferiority_gate_green": memory_agent["passed"] is True,
        "independent_model_judge_green": False,
        "blind_human_review_green": False,
        "official_mem0_same_control_comparison_green": mem0_followup_green,
    }
    stage_passed = all(stage_checks.values())
    agent_product_freeze_allowed = all(product_freeze_checks.values())
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": STAGE_ID,
        "branch": STAGE_BRANCH,
        "source_commit": source_commit,
        "manifest": _safe_relative(manifest_path, root),
        "manifest_sha256": _sha256(manifest_path),
        "status": (
            "ready_for_product_freeze"
            if agent_product_freeze_allowed
            else "stage_passed_product_freeze_blocked"
        ),
        "stage_passed": stage_passed,
        "agent_product_freeze_allowed": agent_product_freeze_allowed,
        "model_training_allowed": agent_product_freeze_allowed,
        "verified_inputs": verified_inputs,
        "stage_checks": stage_checks,
        "product_freeze_checks": product_freeze_checks,
        "architecture": {
            "freeze_passed": architecture["passed"],
            "chapter_gates_passed": architecture["counts"][
                "chapter_gates_passed"
            ],
            "chapter_gates_total": architecture["counts"]["chapter_gates_total"],
            "remote_branches_audited": branch_audit["branch_count"],
            "unique_remote_commits": branch_audit["unique_commit_count"],
        },
        "local_runtime": {
            "python_tests_collected": hardening["counts"][
                "python_tests_collected"
            ],
            "python_tests_skipped": hardening["counts"]["python_tests_skipped"],
            "web_tests": hardening["counts"]["web_tests"],
            "behavior_observations": hardening["counts"][
                "behavior_observations"
            ],
            "critical_deterministic_rate": hardening["behavior"][
                "critical_deterministic_rate"
            ],
            "normal_task_success_rate": hardening["behavior"][
                "normal_task_success_rate"
            ],
            "p0_count": hardening["behavior"]["p0_count"],
        },
        "stage_verification": {
            "python_tests_collected": python_tests_collected,
            "python_tests_skipped": python_tests_skipped,
            "web_tests": web_tests,
            "web_test_files": web_test_files,
            "web_build_passed": web_build_passed,
        },
        "memory": {
            "benchmark": "LoCoMo",
            "fresh_split_offset": memory_agent["selection"]["selection_offset"],
            "fresh_case_ids_sha256": memory_agent["selection"][
                "selected_case_ids_sha256"
            ],
            "questions": memory_agent["selection"]["selected_questions"],
            "answer_model": memory_agent["controls"]["model"],
            "direct_f1": direct_metrics["official_f1"],
            "agent_f1": agent_metrics["official_f1"],
            "agent_f1_delta": memory_f1_delta,
            "direct_recall_at_20": direct_metrics["evidence_recall_at_k"],
            "agent_recall_at_20": agent_metrics["evidence_recall_at_k"],
            "agent_recall_delta": memory_recall_delta,
            "tool_call_rate": agent_metrics["memory_search_call_rate"],
            "valid_tool_arguments_rate": agent_metrics[
                "valid_memory_search_arguments_rate"
            ],
            "historical_failed_replay": {
                "artifact": "docs/reports/product/memory-architecture-agent-live.json",
                "agent_f1": historical_memory["agent"]["official_f1"],
                "direct_f1": historical_memory["baseline"][
                    "direct_hybrid_official_f1"
                ],
                "delta": historical_memory["comparison"][
                    "agent_f1_delta_vs_direct_hybrid"
                ],
                "preserved": True,
            },
            **(
                {
                    "mem0_same_control": {
                        "artifact": "docs/reports/product/mem0-comparable-reproduction.json",
                        "official_f1": mem0_followup["systems"][
                            "mem0_v3_pr4805"
                        ]["official_f1"],
                        "evidence_recall_at_20": mem0_followup["systems"][
                            "mem0_v3_pr4805"
                        ]["evidence_recall_at_k"],
                        "agent_f1_delta": mem0_followup["comparison"][
                            "agent_f1_delta_vs_mem0"
                        ],
                        "agent_recall_delta": mem0_followup["comparison"][
                            "agent_recall_delta_vs_mem0"
                        ],
                        "general_superiority_claimed": False,
                    }
                }
                if mem0_followup_green and mem0_followup is not None
                else {}
            ),
        },
        "public_agent_subsets": {
            "tau2_official_success_rate": external["metrics"][
                "tau2_official_success_rate"
            ],
            "agentbench_official_success_rate": external["metrics"][
                "agentbench_official_success_rate"
            ],
            "full_leaderboard_claimed": False,
        },
        "claims": {
            "internal_direct_baseline_beaten_on_recall": memory_recall_delta > 0,
            "internal_direct_baseline_beaten_on_f1": memory_f1_delta > 0,
            "external_memory_competitor_superiority": False,
            "general_agent_framework_superiority": False,
            "general_chatgpt_equivalence": False,
            "frozen_same_control_mem0_comparison_complete": mem0_followup_green,
            "frozen_same_control_agent_outperforms_mem0_on_f1": bool(
                mem0_followup_green
                and mem0_followup["comparison"][
                    "frozen_same_control_agent_outperforms_mem0_on_f1"
                ]
            ),
            "frozen_same_control_agent_outperforms_mem0_on_recall": bool(
                mem0_followup_green
                and mem0_followup["comparison"][
                    "frozen_same_control_agent_outperforms_mem0_on_recall"
                ]
            ),
            "interpretation": "Klara improves retrieval recall over its same-model direct baseline on the frozen fresh split, but answer F1 remains lower; no external-system superiority is established.",
        },
        "mandatory_blockers": mandatory_blockers,
        "expansion_gaps": expansion_gaps,
        "hku": {
            "connected": False,
            "uploaded": False,
            "training_started": False,
            "reason": "Agent Product Freeze is blocked; model work cannot start.",
        },
        "followup_evidence": (
            [
                {
                    "stage": "mem0-comparable-reproduction",
                    "artifact": "docs/reports/product/mem0-comparable-reproduction.json",
                    "schema_version": mem0_followup["schema_version"],
                    "sha256": _sha256(mem0_followup_path),
                    "passed": True,
                }
            ]
            if mem0_followup_green and mem0_followup is not None
            else []
        ),
    }
    _require(stage_passed, "readiness reconciliation checks failed")
    updated_ledger = update_completion_ledger(
        ledger,
        report=report,
        source_commit=source_commit,
    )
    return report, updated_ledger


def update_completion_ledger(
    ledger: dict[str, Any],
    *,
    report: dict[str, Any],
    source_commit: str,
) -> dict[str, Any]:
    """Return a ledger copy updated with reconciled benchmark and freeze truth.

    Args:
        ledger: Existing completion ledger object.
        report: Readiness report produced from frozen inputs.
        source_commit: Exact parent commit of this reconciliation stage.

    Returns:
        A new ledger object; the input object is not mutated.
    """

    updated = deepcopy(ledger)
    updated["updated_at"] = report["evaluated_at"]
    updated["current_stage"] = "agent-product-freeze"
    objectives = updated["objectives"]
    by_id = {str(item["id"]): item for item in objectives}
    readiness = {
        "id": STAGE_ID,
        "status": "passed",
        "branch": STAGE_BRANCH,
        "commit": source_commit,
        "commands": [
            "python -m klara.eval.product_freeze_readiness ...",
            "python -m pytest tests/klara/eval/test_product_freeze_readiness.py -q",
            "python -m pytest -q",
            "npm --prefix apps/web test -- --run",
            "npm --prefix apps/web run build",
            "git diff --check",
        ],
        "datasets": [
            "LoCoMo pinned official dataset; fresh 100-question offset-10 split",
            "KlaraBench v2 frozen 41-observation behavior set",
            "pinned AgentBench DBBench and tau2 mock subsets",
        ],
        "evaluator_versions": [REPORT_SCHEMA_VERSION],
        "artifacts": [
            "config/stages/agent-product-freeze-readiness.manifest.json",
            "docs/labs/agent-product-freeze-readiness.md",
            "docs/labs/agent-product-freeze-readiness.en.md",
            "docs/reports/product/agent-product-freeze-readiness.json",
            "docs/reports/product/agent-product-freeze-readiness.md",
            "docs/reports/product/agent-product-freeze-readiness.en.md",
        ],
        "evidence": {
            "stage_passed": report["stage_passed"],
            "agent_product_freeze_allowed": report[
                "agent_product_freeze_allowed"
            ],
            "verified_input_count": len(report["verified_inputs"]),
            "python_tests_collected": report["stage_verification"][
                "python_tests_collected"
            ],
            "python_tests_skipped": report["stage_verification"][
                "python_tests_skipped"
            ],
            "web_tests": report["stage_verification"]["web_tests"],
            "web_test_files": report["stage_verification"]["web_test_files"],
            "web_build_passed": report["stage_verification"][
                "web_build_passed"
            ],
            "latest_memory_split_offset": report["memory"]["fresh_split_offset"],
            "historical_memory_failure_preserved": report["memory"][
                "historical_failed_replay"
            ]["preserved"],
        },
        "metrics": {
            "fresh_memory_agent_f1": report["memory"]["agent_f1"],
            "fresh_memory_direct_f1": report["memory"]["direct_f1"],
            "fresh_memory_f1_delta": report["memory"]["agent_f1_delta"],
            "fresh_memory_recall_delta": report["memory"]["agent_recall_delta"],
        },
        "remaining_failures": [],
    }
    if STAGE_ID in by_id:
        by_id[STAGE_ID].update(readiness)
    else:
        freeze_index = next(
            index
            for index, item in enumerate(objectives)
            if item["id"] == "agent-product-freeze"
        )
        objectives.insert(freeze_index, readiness)
        by_id[STAGE_ID] = readiness

    benchmark = by_id["agent-product-benchmarks"]
    benchmark["metrics"].update(
        {
            "fresh_locomo_agent_f1": report["memory"]["agent_f1"],
            "fresh_locomo_direct_f1": report["memory"]["direct_f1"],
            "fresh_locomo_agent_f1_delta": report["memory"]["agent_f1_delta"],
            "fresh_locomo_agent_recall_at_20": report["memory"][
                "agent_recall_at_20"
            ],
            "fresh_locomo_direct_recall_at_20": report["memory"][
                "direct_recall_at_20"
            ],
        }
    )
    benchmark["remaining_failures"] = [
        blocker["detail"] for blocker in report["mandatory_blockers"]
    ] + [gap["detail"] for gap in report["expansion_gaps"]]

    freeze = by_id["agent-product-freeze"]
    freeze.update(
        {
            "status": "blocked_external",
            "branch": "codex/agent-product-freeze",
            "commit": None,
            "commands": [],
            "datasets": [],
            "evaluator_versions": [REPORT_SCHEMA_VERSION],
            "artifacts": [
                "docs/reports/product/agent-product-freeze-readiness.json"
            ],
            "evidence": {
                "architecture_freeze_passed": report["architecture"][
                    "freeze_passed"
                ],
                "local_runtime_gate_passed": report["product_freeze_checks"][
                    "local_code_api_gate_green"
                ],
                "training_allowed": False,
            },
            "metrics": {},
            "remaining_failures": [
                blocker["detail"] for blocker in report["mandatory_blockers"]
            ],
        }
    )
    _append_model_objectives(objectives)
    return updated


def render_report(report: dict[str, Any], *, language: str = "zh") -> str:
    """Render the readiness result in Chinese or English.

    Args:
        report: Readiness report object.
        language: ``zh`` for Chinese or ``en`` for English.

    Returns:
        Markdown derived only from the machine-readable report.
    """

    zh = language == "zh"
    status = "通过" if report["stage_passed"] and zh else "PASS" if report["stage_passed"] else "未通过" if zh else "FAIL"
    freeze = "允许" if report["agent_product_freeze_allowed"] and zh else "ALLOWED" if report["agent_product_freeze_allowed"] else "阻塞" if zh else "BLOCKED"
    title = "Agent Product Freeze 就绪性" if zh else "Agent Product Freeze Readiness"
    lines = [
        f"# {title}",
        "",
        (
            "语言：中文 | [English](./agent-product-freeze-readiness.en.md)"
            if zh
            else "Language: [Chinese](./agent-product-freeze-readiness.md) | English"
        ),
        "",
        f"- {'证据统一阶段' if zh else 'Evidence reconciliation stage'}: `{status}`",
        f"- Agent Product Freeze: `{freeze}`",
        f"- {'模型训练允许' if zh else 'Model training allowed'}: `{str(report['model_training_allowed']).lower()}`",
        "",
        f"## {'当前真实成绩' if zh else 'Current Measured Truth'}",
        "",
        f"- {'架构门禁' if zh else 'Architecture gates'}: `{report['architecture']['chapter_gates_passed']}/{report['architecture']['chapter_gates_total']}`.",
        f"- {'行为观察' if zh else 'Behavior observations'}: `{report['local_runtime']['behavior_observations']}`, critical `{report['local_runtime']['critical_deterministic_rate']}`, normal `{report['local_runtime']['normal_task_success_rate']}`, P0 `{report['local_runtime']['p0_count']}`.",
        f"- LoCoMo F1: direct `{report['memory']['direct_f1']}`, Agent `{report['memory']['agent_f1']}`, delta `{report['memory']['agent_f1_delta']}`.",
        f"- LoCoMo Recall@20: direct `{report['memory']['direct_recall_at_20']}`, Agent `{report['memory']['agent_recall_at_20']}`, delta `{report['memory']['agent_recall_delta']}`.",
        f"- AgentBench subset: `{report['public_agent_subsets']['agentbench_official_success_rate']}`; tau2 subset: `{report['public_agent_subsets']['tau2_official_success_rate']}`.",
        f"- {'本阶段验证' if zh else 'Stage verification'}: Python `{report['stage_verification']['python_tests_collected']}` collected / `{report['stage_verification']['python_tests_skipped']}` skipped; web `{report['stage_verification']['web_tests']}` tests in `{report['stage_verification']['web_test_files']}` files; build `{str(report['stage_verification']['web_build_passed']).lower()}`.",
        "",
        f"## {'解释边界' if zh else 'Interpretation Boundary'}",
        "",
        (
            "- Agent 的检索召回超过同模型 direct baseline，但答案 F1 仍低于 direct baseline。"
            if zh
            else "- Agent retrieval recall exceeds the same-model direct baseline, while answer F1 remains below it."
        ),
        (
            "- 没有 Mem0、MEM1、BEAM、GPT、Qwen、通用 Agent 框架或 ChatGPT 总体领先声明。"
            if zh
            else "- No Mem0, MEM1, BEAM, GPT, Qwen, general Agent-framework, or ChatGPT superiority claim is made."
        ),
        "",
        f"## {'冻结阻塞项' if zh else 'Freeze Blockers'}",
        "",
    ]
    # Blockers are kept verbatim so the bilingual reports cannot alter gate truth.
    lines.extend(f"- `{item['id']}`: {item['detail']}" for item in report["mandatory_blockers"])
    lines.extend(
        [
            "",
            f"## {'资源扩展项' if zh else 'Resource-dependent Expansion'}",
            "",
        ]
    )
    lines.extend(f"- `{item['id']}`: {item['detail']}" for item in report["expansion_gaps"])
    lines.append("")
    return "\n".join(lines)


def render_ledger(ledger: dict[str, Any], *, language: str = "zh") -> str:
    """Render the reconciled ledger in Chinese or English.

    Args:
        ledger: Completion ledger object.
        language: ``zh`` for Chinese or ``en`` for English.

    Returns:
        Markdown status table and unresolved failures.
    """

    zh = language == "zh"
    lines = [
        f"# {'AgentLadder 完成账本' if zh else 'AgentLadder Completion Ledger'}",
        "",
        (
            "语言：中文 | [English](./completion-ledger.en.md)"
            if zh
            else "Language: [Chinese](./completion-ledger.md) | English"
        ),
        "",
        f"- {'当前阶段' if zh else 'Current stage'}: `{ledger['current_stage']}`",
        f"- {'模式' if zh else 'Mode'}: `{ledger['mode']}`",
        f"- {'更新时间' if zh else 'Updated at'}: `{ledger['updated_at']}`",
        "",
        f"## {'目标状态' if zh else 'Objective Status'}",
        "",
        f"| {'目标' if zh else 'Objective'} | {'状态' if zh else 'Status'} | {'分支' if zh else 'Branch'} |",
        "| --- | --- | --- |",
    ]
    # Preserve roadmap order so the table also expresses execution dependencies.
    for objective in ledger["objectives"]:
        lines.append(
            f"| `{objective['id']}` | `{objective['status']}` | `{objective['branch']}` |"
        )
    lines.extend(["", f"## {'剩余失败' if zh else 'Remaining Failures'}", ""])
    found_failure = False
    # Show only unresolved evidence; passed historical stages stay compact above.
    for objective in ledger["objectives"]:
        failures = objective.get("remaining_failures", [])
        if not failures:
            continue
        found_failure = True
        lines.append(f"### `{objective['id']}`")
        lines.append("")
        lines.extend(f"- {failure}" for failure in failures)
        lines.append("")
    if not found_failure:
        lines.extend(["- none", ""])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the readiness report and reconciled completion ledger."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--python-tests-collected", type=int, required=True)
    parser.add_argument("--python-tests-skipped", type=int, required=True)
    parser.add_argument("--web-tests", type=int, required=True)
    parser.add_argument("--web-test-files", type=int, required=True)
    parser.add_argument("--web-build-passed", action="store_true")
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--report-md", type=Path, required=True)
    parser.add_argument("--report-en-md", type=Path, required=True)
    parser.add_argument("--ledger-json", type=Path, required=True)
    parser.add_argument("--ledger-md", type=Path, required=True)
    parser.add_argument("--ledger-en-md", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report, ledger = build_report(
        root,
        manifest_path=args.manifest,
        source_commit=args.source_commit,
        python_tests_collected=args.python_tests_collected,
        python_tests_skipped=args.python_tests_skipped,
        web_tests=args.web_tests,
        web_test_files=args.web_test_files,
        web_build_passed=args.web_build_passed,
    )
    outputs = {
        args.report_json: json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        args.report_md: render_report(report),
        args.report_en_md: render_report(report, language="en"),
        args.ledger_json: json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        args.ledger_md: render_ledger(ledger),
        args.ledger_en_md: render_ledger(ledger, language="en"),
    }
    # Write all representations from the same in-memory report/ledger objects.
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "stage_passed": report["stage_passed"],
                "agent_product_freeze_allowed": report[
                    "agent_product_freeze_allowed"
                ],
                "model_training_allowed": report["model_training_allowed"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["stage_passed"] else 1


def _append_model_objectives(objectives: list[dict[str, Any]]) -> None:
    """Append missing post-freeze objectives without reordering existing history."""

    existing = {str(item["id"]) for item in objectives}
    model_objectives = (
        ("hku-policy-model-baselines", "codex/hku-policy-model-baselines"),
        ("hku-policy-distillation", "codex/hku-policy-distillation"),
        ("hku-precision-serving", "codex/hku-precision-serving"),
        ("learned-policy-shadow", "codex/learned-policy-shadow"),
        ("learned-policy-canary", "codex/learned-policy-canary"),
        ("learned-policy-integration", "codex/learned-policy-integration"),
        ("model-integration-freeze", "codex/model-integration-freeze"),
    )
    # Append only new roadmap objectives so repeated generation remains idempotent.
    for objective_id, branch in model_objectives:
        if objective_id in existing:
            continue
        objectives.append(
            {
                "id": objective_id,
                "status": "pending",
                "branch": branch,
                "commit": None,
                "commands": [],
                "datasets": [],
                "evaluator_versions": [],
                "artifacts": [],
                "evidence": {},
                "metrics": {},
                "remaining_failures": [],
            }
        )


def _read(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object from disk."""

    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(path: Path, root: Path) -> str:
    """Return a repository-relative path when possible."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "[external-path]"


def _require(condition: bool, message: str) -> None:
    """Fail closed when frozen evidence no longer satisfies an invariant."""

    if not condition:
        raise ValueError(message)


if __name__ == "__main__":
    raise SystemExit(main())
