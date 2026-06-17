from agent_ladder.rag.agentic.budget import BudgetManager
from agent_ladder.rag.agentic.normalizer import normalize_request
from agent_ladder.rag.agentic.planner import plan_evidence_search
from agent_ladder.rag.contracts.agentic import SearchUnit


def test_budget_manager_clamps_search_units_and_candidates():
    plan = plan_evidence_search(normalize_request("give me 50 papers"))
    plan = plan.model_copy(update={"search_units": [SearchUnit(provider_id="paper_chunk_bm25", query="x") for _ in range(10)], "candidate_source_budget": 99})
    manager = BudgetManager()
    clamped = manager.clamp_plan(plan)
    assert len(clamped.search_units) == manager.state.max_search_units
    assert clamped.candidate_source_budget == manager.state.max_candidate_sources
    assert manager.state.clamp_events
