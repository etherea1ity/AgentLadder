from __future__ import annotations

from agent_ladder.knowledge.paper.corpus import PaperCorpus
from agent_ladder.knowledge.paper.source_card import PaperSourceCardBuilder
from agent_ladder.rag.agentic.providers import PaperFetchProvider
from agent_ladder.rag.contracts.agentic import EvidenceItem, EvidencePack, FetchRequest, FetchResult, RequestSpec, SearchHit, VisualElement


class EvidenceReader:
    def __init__(self, fetcher: PaperFetchProvider | None = None) -> None:
        self.fetcher = fetcher or PaperFetchProvider()

    def fetch(self, hits: list[SearchHit]) -> list[FetchResult]:
        results: list[FetchResult] = []
        seen: set[str] = set()
        for hit in hits:
            if hit.fetch_id in seen:
                continue
            seen.add(hit.fetch_id)
            results.append(self.fetcher.fetch(FetchRequest(fetch_id=hit.fetch_id, source_type=hit.source_type, paper_id=hit.paper_id)))
        return results


class EvidenceSelector:
    def select(self, results: list[FetchResult], *, budget: int) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        for rank, result in enumerate(results[:budget], start=1):
            visual = None
            evidence_type = "text"
            if result.source_type in {"paper_figure", "paper_table", "paper_visual"}:
                evidence_type = "table" if result.source_type == "paper_table" else "figure"
                visual = VisualElement.model_validate(result.metadata)
            items.append(EvidenceItem(evidence_type=evidence_type, source_id=result.source_id, paper_id=result.paper_id, title=result.title, text=result.text, visual=visual, rank=rank, source_domain=result.source_domain, evidence_role=result.evidence_role, metadata=result.metadata))
        return items


class EvidencePackBuilder:
    def __init__(self) -> None:
        self.card_builder = PaperSourceCardBuilder()

    def build(self, request: RequestSpec, results: list[FetchResult], *, evidence_item_budget: int) -> EvidencePack:
        items = EvidenceSelector().select(results, budget=evidence_item_budget)
        cards = [self.card_builder.from_fetch(result) for result in results[:evidence_item_budget]]
        requested = request.requirements.requested_count or 0
        status = "sufficient" if len(items) >= 2 and (not requested or len({item.paper_id or item.source_id for item in items}) >= min(requested, len(items))) else "weak" if items else "insufficient"
        domains = sorted({item.source_domain for item in items})
        by_domain: dict[str, list[str]] = {}
        for item in items:
            by_domain.setdefault(item.source_domain, []).append(item.source_id)
        return EvidencePack(question=request.original_query, canonical_query_en=request.canonical_query_en, items=items, source_cards=cards, budget={"evidence_item_budget": evidence_item_budget}, evidence_status=status, source_domains=domains, evidence_by_domain=by_domain)
