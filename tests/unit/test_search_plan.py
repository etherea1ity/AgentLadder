from agent_ladder.rag.agentic.normalizer import normalize_request
from agent_ladder.rag.agentic.planner import plan_evidence_search


def test_search_plan_uses_candidate_budget_larger_than_requested_count():
    plan = plan_evidence_search(normalize_request("give me 10 Agentic RAG papers"))
    assert plan.final_source_count == 10
    assert plan.candidate_source_budget >= 40
    assert len(plan.search_units) >= 3
