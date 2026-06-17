from __future__ import annotations

from collections import defaultdict
from time import perf_counter

from agent_ladder.rag.agentic.failure import FailurePolicyHandler
from agent_ladder.rag.agentic.planner import rewrite_query
from agent_ladder.knowledge.paper.corpus import PaperCorpus
from agent_ladder.rag.agentic.providers import LocalKnowledgeSearchProvider, PaperSearchProvider
from agent_ladder.rag.contracts.agentic import EvidenceSearchPlan, RetrievalAttempt, SearchHit, SearchRequest, SearchUnit


class MultiPathRetriever:
    def __init__(self, providers: dict[str, PaperSearchProvider] | None = None, failure_policy: FailurePolicyHandler | None = None, corpus: PaperCorpus | None = None) -> None:
        self.providers = providers or {}
        self.failure_policy = failure_policy or FailurePolicyHandler()
        self.corpus = corpus

    def retrieve(self, plan: EvidenceSearchPlan) -> tuple[list[SearchHit], list[RetrievalAttempt], EvidenceSearchPlan]:
        hits, attempts = self._execute(plan.search_units)
        if _weak(hits) and self.failure_policy.allow_query_rewrite():
            rewritten = rewrite_query(plan.canonical_query_en)
            rewritten_units = [unit.model_copy(update={"query": rewritten}) for unit in plan.search_units]
            retry_hits, retry_attempts = self._execute(rewritten_units)
            attempts.append(RetrievalAttempt(stage="rewrite", query=rewritten, hit_count=len(retry_hits), selected_count=len(retry_hits), metadata={"from": plan.canonical_query_en}))
            hits.extend(retry_hits)
            attempts.extend(retry_attempts)
            plan = plan.model_copy(update={"canonical_query_en": rewritten, "search_units": rewritten_units})
        fused = rrf_fusion(hits)
        attempts.append(RetrievalAttempt(stage="fusion", hit_count=len(hits), selected_count=len(fused), metadata={"method": "rrf"}))
        deduped = paper_level_dedup(fused)
        attempts.append(RetrievalAttempt(stage="dedup", hit_count=len(fused), selected_count=len(deduped), metadata={"key": "paper_id"}))
        reranked = diversity_rerank(deduped) if plan.diversity_requirements else deduped
        if any(unit.provider_id == "paper_visual_caption" for unit in plan.search_units):
            visuals = [hit for hit in reranked if hit.source_type in {"paper_figure", "paper_table", "paper_visual"}]
            non_visuals = [hit for hit in reranked if hit.source_type not in {"paper_figure", "paper_table", "paper_visual"}]
            if visuals:
                reranked = [visuals[0], *non_visuals, *visuals[1:]]
        attempts.append(RetrievalAttempt(stage="rerank", hit_count=len(deduped), selected_count=len(reranked), metadata={"diversity": plan.diversity_requirements}))
        return reranked[: plan.candidate_source_budget], attempts, plan

    def _execute(self, units: list[SearchUnit]) -> tuple[list[SearchHit], list[RetrievalAttempt]]:
        all_hits: list[SearchHit] = []
        attempts: list[RetrievalAttempt] = []
        for unit in units:
            started = perf_counter()
            provider = self.providers.get(unit.provider_id) or _provider_for_unit(unit, self.corpus)
            try:
                hits = provider.search(SearchRequest(query=unit.query, canonical_query_en=unit.query, provider_id=unit.provider_id, top_k=unit.top_k, filters=unit.filters, source_domain=unit.source_domain))
                latency = int((perf_counter() - started) * 1000)
                all_hits.extend(hits)
                attempts.append(RetrievalAttempt(stage="search", provider_id=unit.provider_id, query=unit.query, hit_count=len(hits), selected_count=len(hits), latency_ms=latency))
            except Exception as exc:
                attempts.append(RetrievalAttempt(stage="search", provider_id=unit.provider_id, query=unit.query, error=str(exc)))
        return all_hits, attempts


def rrf_fusion(hits: list[SearchHit], k: float = 60.0) -> list[SearchHit]:
    scores: dict[str, float] = defaultdict(float)
    best: dict[str, SearchHit] = {}
    for hit in hits:
        key = f"{hit.source_type}:{hit.source_id}"
        rank = hit.rank or 999
        scores[key] += 1.0 / (k + rank)
        if key not in best or hit.score > best[key].score:
            best[key] = hit
    fused = [best[key].model_copy(update={"score": score}) for key, score in scores.items()]
    fused.sort(key=lambda item: item.score, reverse=True)
    return [hit.model_copy(update={"rank": index + 1}) for index, hit in enumerate(fused)]


def paper_level_dedup(hits: list[SearchHit]) -> list[SearchHit]:
    selected: dict[str, SearchHit] = {}
    visual_hits: dict[str, SearchHit] = {}
    for hit in hits:
        if hit.source_type in {"paper_figure", "paper_table", "paper_visual"}:
            visual_hits[hit.source_id] = hit
            continue
        key = hit.paper_id or hit.source_id
        if key not in selected or hit.score > selected[key].score:
            selected[key] = hit
    result = [*selected.values(), *visual_hits.values()]
    result.sort(key=lambda item: item.score, reverse=True)
    return [hit.model_copy(update={"rank": index + 1}) for index, hit in enumerate(result)]


def diversity_rerank(hits: list[SearchHit]) -> list[SearchHit]:
    seen_domains: set[str] = set()
    first_pass: list[SearchHit] = []
    rest: list[SearchHit] = []
    for hit in hits:
        domain = str(hit.metadata.get("domain") or "")
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            first_pass.append(hit)
        else:
            rest.append(hit)
    result = [*first_pass, *rest]
    return [hit.model_copy(update={"rank": index + 1}) for index, hit in enumerate(result)]


def _weak(hits: list[SearchHit]) -> bool:
    return len(hits) < 2 or sum(hit.score for hit in hits) < 0.1


def _provider_for_unit(unit: SearchUnit, corpus: PaperCorpus | None):
    if unit.provider_id in {"project_docs_bm25", "chapter_docs_bm25"}:
        return LocalKnowledgeSearchProvider(unit.provider_id)
    return PaperSearchProvider(unit.provider_id, corpus=corpus)
