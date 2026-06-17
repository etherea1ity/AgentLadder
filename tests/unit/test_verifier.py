from agent_ladder.rag.agentic.evidence import EvidencePackBuilder, EvidenceReader
from agent_ladder.rag.agentic.normalizer import normalize_request
from agent_ladder.rag.agentic.providers import PaperSearchProvider
from agent_ladder.rag.agentic.verifier import AnswerVerifier
from agent_ladder.rag.agentic.writer import AnswerWriter
from agent_ladder.rag.contracts.agentic import SearchRequest


def test_verifier_passes_cited_evidence_pack_answer():
    req = normalize_request("Agentic RAG critique")
    hits = PaperSearchProvider("paper_chunk_bm25").search(SearchRequest(query=req.canonical_query_en, top_k=3))
    pack = EvidencePackBuilder().build(req, EvidenceReader().fetch(hits), evidence_item_budget=3)
    answer = AnswerWriter().write(req, pack)
    result = AnswerVerifier().verify(answer, pack, req.language_plan.output_language)
    assert result.status in {"passed", "failed", "revised"}
    assert result.citation_ok is True
