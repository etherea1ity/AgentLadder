from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_nonexistent_real_query_is_insufficient():
    result = AgenticRAGRuntime(paper_root="data/papers").run("qwerty_nonexistent_agent_ladder_topic", save_trace=False)
    assert result.answer_frame.mode == "insufficient_info" or result.state.evidence_pack.evidence_status == "insufficient"
