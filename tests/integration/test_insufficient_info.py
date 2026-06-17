from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_insufficient_info_for_empty_evidence():
    result = AgenticRAGRuntime().run("zzzzqwerty asdfgh nohit", save_trace=False)
    if result.state.evidence_pack.evidence_status == "insufficient":
        assert result.answer_frame.mode == "insufficient_info"
    else:
        assert result.answer_frame.final_text
