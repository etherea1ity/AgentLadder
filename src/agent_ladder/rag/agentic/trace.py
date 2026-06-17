from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from agent_ladder.rag.contracts.agentic import DecisionRecord, WorkflowState


class DecisionTracer:
    def __init__(self) -> None:
        self.decisions: list[DecisionRecord] = []

    def record(self, *, node_name: str, decision_type: str, reason: str, input_summary: str = "", output_summary: str = "", confidence: float | None = None, alternatives: list[str] | None = None, latency_ms: int | None = None, error: str | None = None) -> DecisionRecord:
        record = DecisionRecord(
            node_name=node_name,
            decision_type=decision_type,
            reason=reason,
            input_summary=input_summary,
            output_summary=output_summary,
            confidence=confidence,
            alternatives=alternatives or [],
            latency_ms=latency_ms,
            error=error,
        )
        self.decisions.append(record)
        return record

    def extend_state(self, state: WorkflowState) -> WorkflowState:
        return state.model_copy(update={"decisions": [*state.decisions, *self.decisions]})


def save_workflow_trace(path: str | Path, state: WorkflowState, *, question: str, final_text: str, latency_ms: int | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "schema_version": "v0.3",
        "ask": {"question": question},
        "answer": {"answer": final_text},
        "run": {"run_id": state.workflow_id, "latency_ms": latency_ms},
        "run_mode": state.run_mode,
        "route": state.route.model_dump(mode="json") if state.route else None,
        "workflow_state": state.model_dump(mode="json"),
        "request_spec": state.request.model_dump(mode="json") if state.request else None,
        "search_plan": state.search_plan.model_dump(mode="json") if state.search_plan else None,
        "retrieval_attempts": [a.model_dump(mode="json") for a in state.retrieval_attempts],
        "evidence_pack": state.evidence_pack.model_dump(mode="json") if state.evidence_pack else None,
        "answer_frame": state.answer_frame.model_dump(mode="json") if state.answer_frame else None,
        "verification": state.verification.model_dump(mode="json") if state.verification else None,
        "decisions": [d.model_dump(mode="json") for d in state.decisions],
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


class timer:
    def __enter__(self):
        self.start = perf_counter()
        return self

    def __exit__(self, *exc):
        self.latency_ms = int((perf_counter() - self.start) * 1000)
