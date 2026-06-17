from agent_ladder.rag.agentic.evidence import EvidencePackBuilder, EvidenceReader
from agent_ladder.rag.agentic.normalizer import normalize_request
from agent_ladder.rag.agentic.providers import PaperSearchProvider
from agent_ladder.rag.contracts.agentic import SearchRequest


def test_evidence_pack_contains_writer_safe_items_not_raw_chunks():
    req = normalize_request("Agentic RAG evidence verification")
    hits = PaperSearchProvider("paper_chunk_bm25").search(SearchRequest(query=req.canonical_query_en, top_k=2))
    results = EvidenceReader().fetch(hits)
    pack = EvidencePackBuilder().build(req, results, evidence_item_budget=2)
    assert pack.items
    assert pack.evidence_status in {"sufficient", "weak"}
    assert not hasattr(pack, "raw_chunks")
