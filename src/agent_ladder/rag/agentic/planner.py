from __future__ import annotations

from agent_ladder.rag.contracts.agentic import EvidenceSearchPlan, RequestSpec, SearchUnit


def plan_evidence_search(request: RequestSpec) -> EvidenceSearchPlan:
    count = request.requirements.requested_count or 5
    source_budget = min(60, max(20, count * 5))
    chunk_budget = min(120, max(30, count * 8))
    evidence_budget = min(24, max(6, count * 2))
    query = request.canonical_query_en
    units = [
        SearchUnit(provider_id="paper_overview_bm25", query=query, top_k=min(20, source_budget), source_domain="paper_corpus", purpose="paper_overview_keyword"),
        SearchUnit(provider_id="paper_chunk_bm25", query=query, top_k=min(30, chunk_budget), source_domain="paper_corpus", purpose="paper_chunk_keyword"),
        SearchUnit(provider_id="paper_metadata", query=query, top_k=min(20, source_budget), source_domain="paper_corpus", purpose="paper_metadata_filter"),
        SearchUnit(provider_id="chapter_docs_bm25", query=request.query_variants_by_domain.get("chapter_docs", request.original_query), top_k=8, source_domain="chapter_docs", purpose="chapter_knowledge"),
        SearchUnit(provider_id="project_docs_bm25", query=request.query_variants_by_domain.get("project_docs", request.original_query), top_k=8, source_domain="project_docs", purpose="project_knowledge"),
    ]
    if any(term in request.original_query.lower() for term in ["figure", "table", "visual", "图", "图片", "表格"]):
        units.append(SearchUnit(provider_id="paper_visual_caption", query=query, top_k=20, source_domain="paper_visuals", purpose="visual_caption"))
    return EvidenceSearchPlan(
        original_query=request.original_query,
        canonical_query_en=query,
        search_units=units,
        final_source_count=count,
        candidate_source_budget=source_budget,
        candidate_chunk_budget=chunk_budget,
        evidence_item_budget=evidence_budget,
        diversity_requirements=["domain", "method_tags"] if request.requirements.need_diversity else [],
    )


def rewrite_query(query: str) -> str:
    additions = []
    lower = query.lower()
    if "agentic rag" in lower:
        additions.extend(["controlled retrieval", "query planning", "evidence verification", "self-rag"])
    if "figure" in lower or "visual" in lower:
        additions.extend(["caption", "table", "multimodal document"])
    return " ".join([query, *additions]).strip()
