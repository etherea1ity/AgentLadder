from agent_ladder.knowledge.paper.corpus import PaperCorpus


def test_paper_corpus_loader_reads_three_fixture_papers():
    corpus = PaperCorpus()
    papers = corpus.list_papers()
    assert len(papers) >= 3
    assert corpus.overview_text("paper_agentic_rag")
    assert corpus.chunks("paper_agentic_rag")
