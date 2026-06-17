from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_requested_count_10_uses_candidate_budget_not_topk_10():
    result = AgenticRAGRuntime(paper_root="data/papers").run("给我 10 篇 Agentic RAG 相关论文，并按路线分类", save_trace=False)
    req = result.state.request
    plan = result.state.search_plan
    assert req.requirements.requested_count == 10
    assert plan.final_source_count == 10
    assert plan.candidate_source_budget > plan.final_source_count
    assert len(result.answer_frame.sources) <= 10
    assert result.state.retrieval_attempts
    assert result.state.evidence_pack is not None
    assert result.state.verification is not None
