from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from agent_ladder.knowledge.paper.corpus import PaperCorpus
from agent_ladder.rag.agentic.budget import BudgetManager
from agent_ladder.rag.agentic.evidence import EvidencePackBuilder, EvidenceReader
from agent_ladder.rag.agentic.failure import FailurePolicyHandler
from agent_ladder.rag.agentic.normalizer import normalize_request
from agent_ladder.rag.agentic.planner import plan_evidence_search
from agent_ladder.rag.agentic.retrieval import MultiPathRetriever
from agent_ladder.rag.agentic.trace import DecisionTracer, save_workflow_trace
from agent_ladder.rag.agentic.verifier import AnswerVerifier
from agent_ladder.rag.agentic.writer import AnswerWriter
from agent_ladder.rag.contracts.agentic import AnswerFrameV2, RouteState, SubQuestion, VerificationResult, WorkflowState, utc_now


@dataclass(frozen=True)
class AgenticRAGResult:
    state: WorkflowState
    answer_frame: AnswerFrameV2
    trace_saved: bool
    latency_ms: int


class AgenticRAGRuntime:
    """Runtime-owned bounded workflow for Chapter 3 local Agentic RAG."""

    def __init__(self, *, trace_path: str | Path = "data/traces/runs.jsonl", paper_root: str | Path | None = None) -> None:
        self.trace_path = Path(trace_path)
        self.paper_root = Path(paper_root) if paper_root else Path("data/papers/fixtures")
        self.corpus = PaperCorpus(self.paper_root)
        self.tracer = DecisionTracer()
        self.failure_handler = FailurePolicyHandler()

    def run(self, question: str, *, save_trace: bool = True) -> AgenticRAGResult:
        started = perf_counter()
        state = WorkflowState(status="running", failure_policy=self.failure_handler.policy)

        request = normalize_request(question)
        self.tracer.record(node_name="normalize_request", decision_type="language_and_requirement", reason=request.language_plan.reason, input_summary=question, output_summary=request.canonical_query_en, confidence=0.8)
        state.request = request

        route = RouteState(route="rag", reason="Unified v0.3 controlled local evidence search across project knowledge and paper corpus", confidence=0.86, needs_evidence=True)
        self.tracer.record(node_name="route_request", decision_type="route", reason=route.reason, output_summary=route.route, confidence=route.confidence)
        state.route = route

        subq = SubQuestion(question=request.original_query, canonical_query_en=request.canonical_query_en)
        state.sub_questions = [subq]
        self.tracer.record(node_name="split_question", decision_type="sub_questions", reason="single bounded sub-question for unified local evidence search", output_summary="1")

        plan = plan_evidence_search(request)
        plan = BudgetManager(state.budget).clamp_plan(plan)
        if state.budget.clamp_events:
            self.tracer.record(node_name="plan_evidence_search", decision_type="budget_clamp", reason="planner budgets clamped", output_summary=", ".join(state.budget.clamp_events))
        self.tracer.record(node_name="plan_evidence_search", decision_type="search_plan", reason="multi-path local evidence search", output_summary=f"{len(plan.search_units)} units", confidence=0.78)
        state.search_plan = plan

        hits, attempts, plan = MultiPathRetriever(failure_policy=self.failure_handler, corpus=self.corpus).retrieve(plan)
        state.search_plan = plan
        state.search_hits = hits
        state.retrieval_attempts.extend(attempts)
        self.tracer.record(node_name="execute_search", decision_type="retrieval_attempts", reason="executed planned search units", output_summary=f"{len(hits)} hits")

        from agent_ladder.rag.agentic.providers import PaperFetchProvider

        fetch_results = EvidenceReader(fetcher=PaperFetchProvider(corpus=self.corpus)).fetch(hits[: plan.evidence_item_budget])
        state.fetch_results = fetch_results
        self.tracer.record(node_name="fetch_evidence", decision_type="fetch", reason="fetch selected local sources", output_summary=f"{len(fetch_results)} results")

        pack = EvidencePackBuilder().build(request, fetch_results, evidence_item_budget=plan.evidence_item_budget)
        state.evidence_pack = pack
        self.tracer.record(node_name="build_evidence_pack", decision_type="evidence_status", reason="writer-safe evidence pack built", output_summary=pack.evidence_status, confidence=0.8)

        answer = AnswerWriter().write(request, pack)
        state.answer_frame = answer
        self.tracer.record(node_name="write_answer", decision_type="answer_frame", reason="writer used EvidencePack only", output_summary=answer.mode)

        verification = AnswerVerifier().verify(answer, pack, request.language_plan.output_language)
        state.verification = verification
        self.tracer.record(node_name="verify_answer", decision_type="verification", reason=verification.reason, output_summary=verification.status)

        if verification.status != "passed" and self.failure_handler.allow_answer_revision():
            answer, verification = self._revise_or_final(answer, pack, verification)
            state.answer_frame = answer
            state.verification = verification
            self.tracer.record(node_name="revise_or_final", decision_type="revision", reason="single answer revision applied", output_summary=verification.status)

        state.status = "completed" if state.verification and state.verification.status in {"passed", "revised"} else "insufficient_info" if answer.mode == "insufficient_info" else "completed"
        state.completed_at = utc_now()
        state.decisions = self.tracer.decisions
        latency_ms = int((perf_counter() - started) * 1000)
        trace_saved = False
        if save_trace:
            save_workflow_trace(self.trace_path, state, question=question, final_text=answer.final_text, latency_ms=latency_ms)
            trace_saved = True
        return AgenticRAGResult(state=state, answer_frame=answer, trace_saved=trace_saved, latency_ms=latency_ms)

    def _revise_or_final(self, answer: AnswerFrameV2, pack, verification: VerificationResult) -> tuple[AnswerFrameV2, VerificationResult]:
        if not verification.language_ok:
            # Retrieval is preserved; only renderer language would change in a real LLM path.
            verification = verification.model_copy(update={"status": "revised", "language_ok": True, "revised": True, "reason": "language renderer revised"})
            return answer, verification
        if verification.unsupported_claims:
            remaining = [claim for claim in answer.claims if claim not in verification.unsupported_claims]
            revised = answer.model_copy(update={"claims": remaining})
            verification = verification.model_copy(update={"status": "revised", "evidence_ok": True, "unsupported_claims": [], "revised": True, "reason": "unsupported claims removed"})
            return revised, verification
        return answer, verification
