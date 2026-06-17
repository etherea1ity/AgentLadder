from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_requested_count_10_uses_larger_candidate_budget():
    result = AgenticRAGRuntime().run("给我 10 篇 Agentic RAG 相关论文，并按路线分类", save_trace=False)
    assert result.state.search_plan.final_source_count == 10
    assert result.state.search_plan.candidate_source_budget >= 40
    assert len(result.state.evidence_pack.items) <= result.state.search_plan.evidence_item_budget
