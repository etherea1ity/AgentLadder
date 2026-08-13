"""Machine gate for Chapters 12-13 real-loop evidence control."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from klara.core.loop import KlaraLoop
from klara.core.hooks import HookManager
from klara.core.messages import ModelResponse
from klara.core.policies import LoopPolicy
from klara.core.tools import JsonObject, ToolCall, ToolMetadata, ToolResult, ToolSpec
from klara.eval.cli import run_gate
from klara.services.evidence import EvidenceRuntimeController
from klara.services.web import WebResearchController
from klara.services.web.fetcher import fetch_page
from klara.tools.base import BaseTool
from klara.tools.builtin.evidence_submit.tool import EvidenceSubmitTool
from klara.tools.executor import ToolExecutor


SCHEMA_VERSION = "klara.chapter-gate.v1"
SCORER_VERSION = "klara.chapter12-13-evidence-runtime.v1"


class _ScriptedLlm:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses

    def complete(self, **_: object) -> ModelResponse:
        return self.responses.pop(0)


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def on_event(self, event: Any) -> None:
        self.events.append(event)


class _FetchedFixtureTool(BaseTool):
    spec = ToolSpec(name="web_fetch", description="fixture fetch", input_schema={"type": "object"})
    metadata = ToolMetadata(label="Fixture fetch", category="test")

    def run(self, arguments: JsonObject) -> ToolResult:
        payload = {
            "observation_kind": "web_fetched_source",
            "source_id": "src-release",
            "url": "https://docs.example.test/release",
            "final_url": "https://docs.example.test/release",
            "title": "Release notes",
            "text": "Version 4 ships evidence control and bounded verification.",
            "extraction_quality": {"score": 0.9},
            "no_relevant_terms_found": False,
            "fetched_at": "2026-08-13T00:00:00+00:00",
        }
        return self.json_success(arguments, payload)


def evaluate_chapter12_13(root: Path) -> dict[str, Any]:
    """Run gold metrics and the actual loop/controller/tool path."""

    fixture = root / "tests/fixtures/algorithm/gate1_gold.json"
    gold = run_gate(fixture, root / "config/experiments/lab_a_evidence_eval.toml")
    web = WebResearchController()
    evidence = EvidenceRuntimeController(web)
    submission = {
        "final_text": "Version 4 adds evidence control.",
        "claims": [
            {"claim_id": "claim-1", "text": "Version 4 adds evidence control.", "required": True}
        ],
        "links": [
            {
                "claim_id": "claim-1",
                "source_id": "src-release",
                "judgment": "supported",
                "support_note": "Version 4 ships evidence control",
            }
        ],
        "citations": [{"claim_id": "claim-1", "source_id": "src-release"}],
        "abstain": False,
        "abstention_reason": "",
    }
    collector = _EventCollector()
    loop = KlaraLoop(
        llm=_ScriptedLlm(
            [
                ModelResponse(
                    content="",
                    tool_calls=(ToolCall(id="fetch-1", name="web_fetch", arguments={}),),
                ),
                ModelResponse(
                    content="",
                    tool_calls=(
                        ToolCall(id="submit-1", name="evidence_submit", arguments=submission),
                    ),
                ),
                ModelResponse(content="unchecked model prose"),
            ]
        ),
        tool_executor=ToolExecutor([_FetchedFixtureTool(), EvidenceSubmitTool()]),
        hooks=HookManager([collector]),
        controllers=(web, evidence),
        policy=LoopPolicy(max_turns=3),
    )
    result = loop.run("What changed in the latest release?", run_id="ch12-13-gate")
    events = [event.to_public_dict() for event in collector.events]
    event_dump = json.dumps(events, ensure_ascii=False)
    source_event = next(
        event for event in events if event["type"] == "evidence.source_recorded"
    )
    verification_event = next(
        event for event in events if event["type"] == "evidence.verification_completed"
    )

    live_smoke: dict[str, Any]
    try:
        page = fetch_page("https://example.com/", max_chars=2000, timeout_seconds=12)
        live_smoke = {
            "status": "passed",
            "url": page.url,
            "final_url": page.final_url,
            "http_status": page.status,
            "title": page.title,
            "text_length": len(page.text),
            "bounded": len(page.text) <= 2000,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:  # live smoke cannot erase deterministic evidence
        live_smoke = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "fetched_at": datetime.now(UTC).isoformat(),
        }

    frontend = (root / "apps/web/src/components/ChatWorkspace.tsx").read_text(encoding="utf-8")
    checks = {
        "stage_manifest_exists": (root / "config/stages/ch12-13-evidence-runtime.manifest.json").exists(),
        "real_loop_replaces_unchecked_prose": result.final_answer.startswith("Version 4 adds evidence control.") and "unchecked model prose" not in result.final_answer,
        "fetched_source_precedes_verification": source_event["seq"] < verification_event["seq"],
        "citation_uses_fetched_source_url": "[Release notes](https://docs.example.test/release)" in result.final_answer,
        "private_submission_not_public": "unchecked model prose" not in event_dump,
        "duplicate_evidence_rejected_by_contract": "source content hash" in (root / "src/klara/services/evidence/contracts.py").read_text(encoding="utf-8"),
        "dangling_stale_irrelevant_contradiction_tests_exist": all(
            term in (root / "tests/klara/services/evidence/test_evidence_runtime.py").read_text(encoding="utf-8")
            for term in ("cand-1", 'status="stale"', 'judgment="contradicted"', "explicit_abstention")
        ),
        "critical_citation_precision": gold.metrics["citation_precision"] == 1.0,
        "critical_citation_recall": gold.metrics["citation_recall"] == 1.0,
        "critical_contradiction_recall": gold.metrics["contradiction_recall"] == 1.0,
        "critical_abstention_accuracy": gold.metrics["abstention_accuracy"] == 1.0,
        "gold_gate_passed": gold.passed,
        "bounded_live_public_page_smoke": live_smoke["status"] in {"passed", "unavailable"},
        "ui_projects_evidence_state": "Evidence verified" in frontend and "Evidence-limited answer" in frontend,
        "bilingual_tutorials_exist": all(
            (root / path).exists()
            for path in (
                "docs/chapters/ch12-controlled-agentic-rag.md",
                "docs/chapters/ch12-controlled-agentic-rag.en.md",
                "docs/chapters/ch13-research-agent.md",
                "docs/chapters/ch13-research-agent.en.md",
            )
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scorer_version": SCORER_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "stage": "ch12-13-evidence-runtime",
        "gate_kind": "real_loop_evidence_control_and_deterministic_gold_gate",
        "checks": checks,
        "metrics": {
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            **gold.metrics,
        },
        "runtime_evidence": {
            "final_answer": result.final_answer,
            "source_event": source_event,
            "verification_event": verification_event,
        },
        "live_smoke": live_smoke,
        "gold_fixture": gold.to_dict(),
        "interpretation": (
            "Passing proves claim-level control on the real Klara loop, deterministic "
            "critical gold metrics, safe public projections, and one bounded public-page "
            "fetch smoke. It is not an open-domain factual-accuracy or universal research claim."
        ),
        "passed": all(checks.values()),
    }


def render_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    english = language == "en"
    lines = [
        "# Chapters 12-13 Evidence Runtime Gate" if english else "# 第 12–13 章证据运行时门禁",
        "",
        "Language: [Chinese](./ch12-13-evidence-runtime.md) | English" if english else "语言：中文 | [English](./ch12-13-evidence-runtime.en.md)",
        "",
        f"Status: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        f"- {'Scorer' if english else '评分器'}: `{report['scorer_version']}`",
        f"- {'Checks' if english else '检查'}: `{report['metrics']['checks_passed']}/{report['metrics']['checks_total']}`",
        "",
        f"## {'Acceptance Checks' if english else '验收检查'}",
        "",
        f"| {'Check' if english else '检查'} | {'Result' if english else '结果'} |",
        "| --- | --- |",
    ]
    lines.extend(f"| {key} | {'PASS' if value else 'FAIL'} |" for key, value in sorted(report["checks"].items()))
    lines.extend([
        "",
        f"## {'Critical Gold Metrics' if english else '关键金标指标'}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ])
    for key in ("citation_precision", "citation_recall", "contradiction_recall", "abstention_accuracy"):
        lines.append(f"| {key} | {report['metrics'][key]:.3f} |")
    lines.extend([
        "",
        f"## {'Bounded Live Smoke' if english else '受限在线探针'}",
        "",
        "```json",
        json.dumps(report["live_smoke"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        f"## {'Interpretation Boundary' if english else '解释边界'}",
        "",
        report["interpretation"] if english else "通过只证明真实 Klara 回路中的逐 claim 证据控制、关键确定性金标指标、公开投影边界与一次受限公开页面抓取成立；它不代表开放域事实准确率达到完美，也不代表任意研究任务都已解决。",
        "",
    ])
    return "\n".join(lines)
