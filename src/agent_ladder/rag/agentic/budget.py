from __future__ import annotations

from agent_ladder.rag.contracts.agentic import BudgetState, EvidenceSearchPlan


class BudgetManager:
    """Clamp planner budgets so user count requests do not become top-k loops."""

    def __init__(self, state: BudgetState | None = None) -> None:
        self.state = state or BudgetState()

    def clamp_plan(self, plan: EvidenceSearchPlan) -> EvidenceSearchPlan:
        updates = {}
        if len(plan.search_units) > self.state.max_search_units:
            self.state.clamp_events.append(f"search_units:{len(plan.search_units)}->{self.state.max_search_units}")
            updates["search_units"] = plan.search_units[: self.state.max_search_units]
        if plan.candidate_source_budget > self.state.max_candidate_sources:
            self.state.clamp_events.append(f"candidate_source_budget:{plan.candidate_source_budget}->{self.state.max_candidate_sources}")
            updates["candidate_source_budget"] = self.state.max_candidate_sources
        if plan.candidate_chunk_budget > self.state.max_candidate_chunks:
            self.state.clamp_events.append(f"candidate_chunk_budget:{plan.candidate_chunk_budget}->{self.state.max_candidate_chunks}")
            updates["candidate_chunk_budget"] = self.state.max_candidate_chunks
        if plan.evidence_item_budget > self.state.max_evidence_items:
            self.state.clamp_events.append(f"evidence_item_budget:{plan.evidence_item_budget}->{self.state.max_evidence_items}")
            updates["evidence_item_budget"] = self.state.max_evidence_items
        for unit in updates.get("search_units", plan.search_units):
            if unit.top_k > 100:
                self.state.clamp_events.append(f"{unit.provider_id}.top_k:{unit.top_k}->100")
        return plan.model_copy(update=updates) if updates else plan
