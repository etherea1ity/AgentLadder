from agent_ladder.knowledge.paper.corpus import PaperCorpus
from agent_ladder.rag.agentic.providers import PaperSearchProvider
from agent_ladder.rag.contracts.agentic import SearchRequest


def test_real_corpus_search_providers_find_agentic_rag():
    corpus = PaperCorpus("data/papers")
    hits = PaperSearchProvider("paper_overview_bm25", corpus=corpus).search(SearchRequest(query="agentic rag", canonical_query_en="agentic rag", top_k=5))
    assert hits
    assert all(hit.source_domain == "paper_corpus" for hit in hits)
