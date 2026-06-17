from agent_ladder.knowledge.paper.corpus import PaperCorpus


def test_real_corpus_root_loads_processed_papers():
    corpus = PaperCorpus("data/papers")
    assert len(corpus.list_papers()) >= 10
    assert corpus.get_paper("paper_001") is not None
