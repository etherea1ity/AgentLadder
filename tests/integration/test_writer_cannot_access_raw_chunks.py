from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_writer_cannot_access_raw_chunks_boundary():
    result = AgenticRAGRuntime().run("Agentic RAG", save_trace=False)
    pack = result.state.evidence_pack
    assert pack is not None
    assert not hasattr(pack, "raw_chunks")
    assert result.answer_frame.evidence_items == pack.items
