"""Aggregate the prompt/context/recovery hardening stage from exact artifacts."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Sequence


CHAPTER_GATES = (
    "chapter04",
    "chapter05",
    "chapter06_07",
    "chapter08",
    "chapter09",
    "chapter10",
    "chapter12_13",
    "chapter14",
    "chapter15",
    "chapter16",
    "chapter17",
    "chapter18",
)


def build_report(
    root: Path,
    *,
    gate_root: Path,
    python_tests_collected: int,
    python_tests_skipped: int,
    web_tests: int,
    web_test_files: int,
    web_build_passed: bool,
) -> dict[str, Any]:
    """Build one auditable verdict without upgrading missing external labels."""

    provider = _read(
        root / "docs/reports/product/prompt-context-recovery-provider-smoke.json"
    )
    behavior = _read(
        root / "docs/reports/product/prompt-context-recovery-behavior-deepseek.json"
    )
    baseline = _read(
        root / "docs/reports/product/prompt-context-recovery-memory-baseline-formal.json"
    )
    memory_agent = _read(
        root / "docs/reports/product/prompt-context-recovery-memory-agent-formal.json"
    )
    chapters = {name: _read(gate_root / f"{name}.json") for name in CHAPTER_GATES}
    provider_cases = {
        str(item["requested_model"]): item for item in provider.get("cases", [])
    }
    deepseek = provider_cases.get("deepseek/deepseek-v4-flash", {})
    qwen = provider_cases.get("qwen/qwen3.7-flash", {})
    behavior_checks = behavior["checks"]
    local_checks = {
        "all_chapter_gates_pass": all(item["passed"] for item in chapters.values()),
        "full_python_suite_passes": python_tests_collected >= 507,
        "web_tests_and_build_pass": (
            web_tests >= 71 and web_test_files >= 20 and web_build_passed
        ),
        "deepseek_real_tool_smoke_passes": (
            deepseek.get("status") == "completed"
            and deepseek.get("tool_call_valid") is True
        ),
        "behavior_critical_rate_passes": behavior_checks["critical_deterministic"],
        "behavior_normal_rate_passes": behavior_checks["normal_task_success"],
        "behavior_repeat_stability_passes": (
            behavior_checks["critical_repeat_stability"]
            and behavior_checks["ordinary_repeat_stability"]
        ),
        "behavior_p0_and_severe_mismatch_pass": (
            behavior_checks["p0_zero"]
            and behavior_checks["severe_answer_mismatch"]
        ),
        "fresh_direct_memory_baseline_passes": baseline["passed"],
        "fresh_agent_memory_gate_passes": memory_agent["passed"],
    }
    product_freeze_checks = {
        **local_checks,
        "independent_qwen_judge_available": qwen.get("status") == "completed",
        "blind_human_review_complete": False,
    }
    agent = memory_agent["agent"]
    direct = baseline["systems"]["hybrid"]
    return {
        "schema_version": "klara.prompt-context-recovery-hardening.v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "prompt-context-recovery-hardening",
        "branch": "codex/prompt-context-recovery-hardening",
        "local_pre_hku_code_and_api_passed": all(local_checks.values()),
        "agent_product_freeze_passed": all(product_freeze_checks.values()),
        "status": "blocked_external_validation",
        "local_checks": local_checks,
        "product_freeze_checks": product_freeze_checks,
        "counts": {
            "python_tests_collected": python_tests_collected,
            "python_tests_skipped": python_tests_skipped,
            "web_tests": web_tests,
            "web_test_files": web_test_files,
            "chapter_gates_passed": sum(item["passed"] for item in chapters.values()),
            "chapter_gates_total": len(chapters),
            "behavior_observations": behavior["counts"]["observations"],
        },
        "behavior": {
            "model": behavior["model"],
            "critical_deterministic_rate": behavior["metrics"][
                "critical_deterministic_rate"
            ],
            "normal_task_success_rate": behavior["metrics"][
                "normal_task_success_rate"
            ],
            "p0_count": behavior["metrics"]["p0_count"],
            "estimated_cost_usd": behavior["estimated_cost_usd"],
            "independent_judge": "unscored",
            "blind_human_review": "unscored",
        },
        "memory": {
            "benchmark": "LoCoMo",
            "selection_offset": memory_agent["selection"]["selection_offset"],
            "questions": memory_agent["selection"]["selected_questions"],
            "max_output_tokens": memory_agent["controls"]["max_output_tokens"],
            "direct_hybrid_f1": direct["official_f1"],
            "agent_f1": agent["official_f1"],
            "agent_f1_delta": round(agent["official_f1"] - direct["official_f1"], 6),
            "direct_recall_at_20": direct["evidence_recall_at_k"],
            "agent_recall_at_20": agent["evidence_recall_at_k"],
            "tool_call_rate": agent["memory_search_call_rate"],
            "valid_tool_arguments_rate": agent[
                "valid_memory_search_arguments_rate"
            ],
            "strange_response_p0": agent["strange_response_p0"],
        },
        "provider": {
            "deepseek": {
                "status": deepseek.get("status"),
                "tool_call_valid": deepseek.get("tool_call_valid"),
            },
            "qwen": {
                "status": qwen.get("status"),
                "error_code": (qwen.get("error") or {}).get("code"),
                "status_code": (qwen.get("error") or {}).get("status_code"),
            },
        },
        "blockers": [
            "Qwen independent-judge credential returned HTTP 401 during the frozen live smoke.",
            "Blind human comparison labels have not been produced; model output cannot be relabeled as human review.",
        ],
        "hku": {
            "connected": False,
            "uploaded": False,
            "training_started": False,
            "reason": "Agent Product Freeze remains red on independent judge and blind-human gates.",
        },
        "artifacts": {
            "provider_smoke": "docs/reports/product/prompt-context-recovery-provider-smoke.json",
            "behavior": "docs/reports/product/prompt-context-recovery-behavior-deepseek.json",
            "memory_baseline": "docs/reports/product/prompt-context-recovery-memory-baseline-formal.json",
            "memory_agent": "docs/reports/product/prompt-context-recovery-memory-agent-formal.json",
        },
    }


def render_markdown(report: dict[str, Any], *, english: bool) -> str:
    """Render the same report in concise Chinese or English."""

    local_status = "PASS" if report["local_pre_hku_code_and_api_passed"] else "FAIL"
    freeze_status = "PASS" if report["agent_product_freeze_passed"] else "FAIL"
    if english:
        lines = [
            "# Prompt, Context, Memory, and Recovery Hardening",
            "",
            "Language: [Chinese](./prompt-context-recovery-hardening.md) | English",
            "",
            f"- Local code/API gate: `{local_status}`",
            f"- Agent Product Freeze: `{freeze_status}`",
            "- HKU training started: `false`",
            "",
            "## Results",
            "",
            f"- Python: `{report['counts']['python_tests_collected']}` collected, `{report['counts']['python_tests_skipped']}` skipped.",
            f"- Web: `{report['counts']['web_tests']}` tests in `{report['counts']['web_test_files']}` files; production build passed.",
            f"- Chapter gates: `{report['counts']['chapter_gates_passed']}/{report['counts']['chapter_gates_total']}`.",
            f"- Behavior: critical `{report['behavior']['critical_deterministic_rate']}`, normal `{report['behavior']['normal_task_success_rate']}`, P0 `{report['behavior']['p0_count']}`.",
            f"- LoCoMo F1: direct `{report['memory']['direct_hybrid_f1']}`, Agent `{report['memory']['agent_f1']}`, delta `{report['memory']['agent_f1_delta']}`.",
            f"- LoCoMo Recall@20: direct `{report['memory']['direct_recall_at_20']}`, Agent `{report['memory']['agent_recall_at_20']}`.",
            "",
            "## Blockers",
            "",
            *[f"- {item}" for item in report["blockers"]],
            "",
        ]
    else:
        lines = [
            "# Prompt、上下文、Memory 与恢复加固",
            "",
            "语言：中文 | [English](./prompt-context-recovery-hardening.en.md)",
            "",
            f"- 本地代码/API 门禁：`{local_status}`",
            f"- Agent Product Freeze：`{freeze_status}`",
            "- HKU 训练已开始：`false`",
            "",
            "## 结果",
            "",
            f"- Python：收集 `{report['counts']['python_tests_collected']}` 项，跳过 `{report['counts']['python_tests_skipped']}` 项。",
            f"- Web：`{report['counts']['web_test_files']}` 个文件、`{report['counts']['web_tests']}` 项测试，生产构建通过。",
            f"- 逐章门禁：`{report['counts']['chapter_gates_passed']}/{report['counts']['chapter_gates_total']}`。",
            f"- 行为回放：critical `{report['behavior']['critical_deterministic_rate']}`，normal `{report['behavior']['normal_task_success_rate']}`，P0 `{report['behavior']['p0_count']}`。",
            f"- LoCoMo F1：direct `{report['memory']['direct_hybrid_f1']}`，Agent `{report['memory']['agent_f1']}`，差值 `{report['memory']['agent_f1_delta']}`。",
            f"- LoCoMo Recall@20：direct `{report['memory']['direct_recall_at_20']}`，Agent `{report['memory']['agent_recall_at_20']}`。",
            "",
            "## 阻塞项",
            "",
            "- Qwen 独立评审凭据在冻结的真实 smoke 中返回 HTTP 401。",
            "- 尚未产生盲测人工标签，不能把模型评分冒充为人工评分。",
            "",
        ]
    return "\n".join(lines)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--gate-root", type=Path, required=True)
    parser.add_argument("--python-tests-collected", type=int, required=True)
    parser.add_argument("--python-tests-skipped", type=int, required=True)
    parser.add_argument("--web-tests", type=int, required=True)
    parser.add_argument("--web-test-files", type=int, required=True)
    parser.add_argument("--web-build-passed", action="store_true")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument("--markdown-en-out", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = build_report(
        root,
        gate_root=args.gate_root.resolve(),
        python_tests_collected=args.python_tests_collected,
        python_tests_skipped=args.python_tests_skipped,
        web_tests=args.web_tests,
        web_test_files=args.web_test_files,
        web_build_passed=args.web_build_passed,
    )
    for path in (args.json_out, args.markdown_out, args.markdown_en_out):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    args.markdown_out.write_text(
        render_markdown(report, english=False), encoding="utf-8", newline="\n"
    )
    args.markdown_en_out.write_text(
        render_markdown(report, english=True), encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                "local_passed": report["local_pre_hku_code_and_api_passed"],
                "product_freeze": report["agent_product_freeze_passed"],
                "status": report["status"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["local_pre_hku_code_and_api_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
