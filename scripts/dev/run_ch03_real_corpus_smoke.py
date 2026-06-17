from __future__ import annotations

from pathlib import Path
from time import perf_counter

from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime

QUERIES = [
    "给我 10 篇 Agentic RAG 相关论文，并按路线分类",
    "Explain Self-RAG in Chinese.",
    "Compare ReAct, Reflexion, and Voyager.",
    "Find papers about retrieval control and query rewriting.",
    "Explain figure-aware RAG in Chinese, include figure if available.",
    "找几篇 world model / spatial world model 相关论文。",
    "This query should not match anything: qwerty_nonexistent_agent_ladder_topic",
]


def main() -> int:
    root = Path("data/papers")
    report_path = root / "quality_reports" / "integration_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Chapter 3 Real Corpus Integration Report", ""]
    all_ok = True
    for query in QUERIES:
        started = perf_counter()
        try:
            result = AgenticRAGRuntime(paper_root=root).run(query, save_trace=True)
            state = result.state
            frame = result.answer_frame
            row = {
                "route": state.route.route if state.route else "unknown",
                "run_mode": state.run_mode,
                "search_units": len(state.search_plan.search_units) if state.search_plan else 0,
                "retrieval_attempts": len(state.retrieval_attempts),
                "source_count": len(frame.sources),
                "evidence_items": len(state.evidence_pack.items) if state.evidence_pack else 0,
                "visual_sources": len(frame.visual_sources),
                "evidence_status": state.evidence_pack.evidence_status if state.evidence_pack else "unknown",
                "verification_status": state.verification.status if state.verification else "unknown",
                "latency_ms": result.latency_ms,
                "trace_saved": result.trace_saved,
            }
            lines.extend([f"## Query: {query}", ""])
            lines.extend([f"- {k}: {v}" for k, v in row.items()])
            lines.append("")
            print(query, row)
        except Exception as exc:
            all_ok = False
            lines.extend([f"## Query: {query}", "", f"- failure: {exc}", ""])
            print(f"FAILED: {query}: {exc}")
        finally:
            _ = perf_counter() - started
    lines.extend(["## Next Fixes", "", "- Review failed or weak queries and improve metadata/chunks rather than weakening verifier."])
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {report_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
