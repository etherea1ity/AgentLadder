# Chapter 3 Domain-aware Local RAG Design

Chapter 3 remains a controlled local research runtime, but the corpus layer must be ready for multiple local and future source domains.

## Source domains

Supported/Reserved source domains:

- `paper_corpus`: paper metadata, overviews, and text chunks.
- `paper_visuals`: figure/table/page visual metadata.
- `project_docs`: future local project documentation provider.
- `chapter_docs`: future Agent Ladder chapter documentation provider.
- `future_web`: reserved for Chapter 5 Web Research providers.

## Evidence roles

Evidence items carry a role so verifiers and future eval can check claim-source alignment:

- `paper_claim`
- `paper_method`
- `paper_result`
- `visual_support`
- `project_fact`
- `chapter_design`

## Runtime flow

1. Router decides allowed `source_domains` for the request.
2. Planner generates domain-specific `SearchUnit` objects.
3. `ProviderRegistry` restricts allowed providers by domain.
4. `SearchRequest.filters` carries metadata hard filters such as domain, year, method tags, and source domain.
5. Search providers produce `SearchHit.source_domain` and `SearchHit.evidence_role`.
6. Fetch providers preserve the same domain and evidence role on `FetchResult`.
7. `EvidencePack` groups evidence by domain through `source_domains` and `evidence_by_domain`.
8. Verifier checks claim-source domain match. Current paper queries allow only `paper_corpus` and `paper_visuals`.
9. `LanguagePlan` uses English canonical query for paper providers and keeps `query_variants_by_domain` for future Chinese/English project docs.

## Current Chapter 3 behavior

- Paper text providers emit `paper_corpus`.
- Visual caption providers emit `paper_visuals`.
- Visual evidence uses `visual_support`.
- Writer still receives only `EvidencePack`.
- No project docs provider is implemented in this task.
- No web provider is implemented in this task.

## Future project docs provider sketch

A future `project_docs` provider should:

- Read only processed documentation indexes.
- Accept `SearchRequest.filters.source_domain = project_docs`.
- Preserve Chinese query variants when source docs are Chinese.
- Return `EvidenceItem.evidence_role = project_fact`.
- Never bypass the runtime or EvidencePack boundary.
