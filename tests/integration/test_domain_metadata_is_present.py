from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_domain_metadata_present_in_evidence_and_sources():
    result = AgenticRAGRuntime(paper_root="data/papers").run("Agentic RAG", save_trace=False)
    assert result.state.evidence_pack.source_domains
    assert all(item.source_domain in {"paper_corpus", "paper_visuals", "project_docs", "chapter_docs"} for item in result.state.evidence_pack.items)
    assert all(card.source_domain in {"paper_corpus", "paper_visuals", "project_docs", "chapter_docs"} for card in result.answer_frame.sources)
