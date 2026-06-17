# Chapter 3 Paper Corpus Audit Plan

## Purpose

This plan records the Phase A audit for connecting the user's local paper material to Chapter 3: Agentic RAG / Klara's Controlled Research Runtime.

The goal is not to redesign the runtime or add PDF processing to the runtime. The goal is to normalize already available or semi-processed paper material into the Chapter 3 Paper Corpus shape that the controlled runtime can search and fetch.

## 1. How Chapter 3 currently reads paper corpus

Current runtime entry:

- `src/agent_ladder/rag/agentic/runtime.py`
- `AgenticRAGRuntime.run(question)` owns the bounded workflow.

Current retrieval path:

- `AgenticRAGRuntime` calls `MultiPathRetriever`.
- `MultiPathRetriever` creates `PaperSearchProvider` for each `SearchUnit`.
- `PaperSearchProvider` reads from `PaperCorpus`.
- `EvidenceReader` uses `PaperFetchProvider` to fetch selected hits.
- `EvidencePackBuilder` converts fetched results into writer-safe `EvidencePack`.
- `AnswerWriter` only sees `EvidencePack`.

Current default corpus root before this task:

- `PaperCorpus()` defaulted to `data/papers/fixtures`.
- `VisualAssetStore()` also defaulted to `data/papers/fixtures`.
- CLI `ask-agentic` did not yet accept `--paper-root`.

Required adjustment:

- Keep fixtures as default test corpus.
- Add an explicit real-corpus path through CLI/config/env.
- Accept `data/papers` as a corpus root and resolve it to `data/papers/processed` for runtime providers.
- Do not move PDF parsing or download logic into providers or runtime.

## 2. How current fixtures are organized

Stable teaching fixtures exist under:

```text
data/papers/fixtures/
├── manifest.jsonl
├── paper_agentic_rag/
├── paper_visual_transformer/
└── paper_world_model/
```

Each fixture paper contains:

```text
metadata.json
overview.md
chunks.jsonl
visuals.jsonl
optional figures/tables assets
```

There is also a larger existing fixture-like processed/raw subtree under:

```text
data/papers/fixtures/processed/
data/papers/fixtures/raw/
```

This will not be deleted. Chapter 3 unit/integration tests should continue to use stable fixtures by default.

## 3. What exists in `data/papers/论文`

During Phase A, the expected source-drop path:

```text
data/papers/论文
```

was checked and was not present in the current workspace snapshot.

However, the project already contains a substantial processed real corpus under:

```text
data/papers/processed/
data/papers/raw/
data/papers/manifest.jsonl
data/papers/manifest_candidates.jsonl
```

Current observed shape:

- `data/papers/processed/paper_001` through `paper_040` exist.
- Each processed paper appears to include at least `metadata.json`, `overview.md`, `chunks.jsonl`, `visuals.jsonl`, `fulltext.txt`, `sections.json`, and optional `figures/` or `pages/` assets.
- `data/papers/manifest.jsonl` contains richer bibliographic metadata than each processed `metadata.json`.
- Some paths in current manifest/visuals use Windows backslashes, which must be normalized to repo-relative POSIX paths for runtime use.

## 4. Gap between existing files and standard corpus schema

Main gaps:

1. `data/papers/论文` source drop is absent, so audit must handle a missing input path without deleting or rewriting anything.
2. `data/papers/processed/<paper_id>/metadata.json` currently contains extraction stats but often lacks required bibliographic fields such as title, authors, year, venue, URL, domains, and method tags.
3. `data/papers/manifest.jsonl` has bibliographic fields but uses older keys such as `downloaded_at` and may use Windows path separators.
4. `chunks.jsonl` rows often lack explicit `source_id`, `source_domain`, `evidence_role`, and normalized metadata fields.
5. `visuals.jsonl` rows may use `title` instead of the current `VisualElement.label`, may omit `source_id`, and may use Windows path separators.
6. `PaperCorpus` currently expects direct child paper directories and does not yet auto-detect `data/papers/processed` when root is `data/papers`.
7. Existing build script includes download/extraction behavior. For this task, the corpus builder must be a migration/normalization tool, not a runtime downloader.

## 5. What can be directly migrated

Directly usable or normalizable:

- Existing `manifest.jsonl` rows.
- Existing `processed/<paper_id>/overview.md`.
- Existing `processed/<paper_id>/chunks.jsonl` text chunks.
- Existing `processed/<paper_id>/visuals.jsonl` visual metadata.
- Existing `processed/<paper_id>/figures`, `tables`, `pages` assets if present.
- Existing `raw/<paper_id>.pdf` only as local existing files; the runtime will not parse them.

## 6. What needs补全 or normalization

Needs补全:

- `metadata.json` should merge manifest bibliographic metadata plus processing and quality sections.
- `manifest.jsonl` should include required standard fields: `source_input_path`, `processed_dir`, `has_overview`, `has_chunks`, `has_visuals`, `created_at`, `updated_at`.
- `chunks.jsonl` should get `source_id`, source domain metadata, evidence role metadata, and POSIX paths where applicable.
- `visuals.jsonl` should get `label`, `source_id`, source domain metadata, evidence role metadata, and path existence validation.
- `quality_reports/` should contain source audit, migration, corpus, validation, and integration reports.
- `indexes/` should contain deterministic lightweight JSON indexes.

Metadata-only cases:

- If a future source-drop candidate has only bibliographic data and no text, it should be recorded as `metadata_only` instead of being skipped silently.
- If PDF/text extraction is unavailable, no runtime parser should be called; report the gap in quality reports.

## 7. Planned files to add or update

Scripts:

```text
scripts/ingest/audit_local_paper_drop.py
scripts/ingest/build_paper_corpus.py
scripts/ingest/validate_paper_corpus.py
scripts/index/build_paper_indexes.py
scripts/dev/run_ch03_real_corpus_smoke.py
```

Runtime/knowledge integration:

```text
src/agent_ladder/knowledge/paper/corpus.py
src/agent_ladder/knowledge/paper/visuals.py
src/agent_ladder/rag/agentic/runtime.py
src/agent_ladder/rag/agentic/providers.py
src/agent_ladder/rag/agentic/retrieval.py
src/agent_ladder/rag/agentic/evidence.py
src/agent_ladder/rag/agentic/verifier.py
src/agent_ladder/rag/agentic/planner.py
src/agent_ladder/rag/agentic/normalizer.py
src/agent_ladder/rag/contracts/agentic.py
src/agent_ladder/rag/contracts/source.py
src/agent_ladder/app/cli/main.py
```

Docs:

```text
docs/architecture/ch03-domain-aware-local-rag.md
docs/architecture/ch03-paper-data-versioning-policy.md
```

Quality outputs:

```text
data/papers/quality_reports/source_audit.json
data/papers/quality_reports/source_audit_report.md
data/papers/quality_reports/migration_report.md
data/papers/quality_reports/corpus_report.md
data/papers/quality_reports/validation_report.md
data/papers/quality_reports/integration_report.md
```

Tests:

```text
tests/unit/test_paper_manifest_schema.py
tests/unit/test_paper_metadata_schema.py
tests/unit/test_paper_chunks_schema.py
tests/unit/test_paper_visuals_schema.py
tests/unit/test_paper_id_generation.py
tests/unit/test_paper_corpus_validation.py
tests/unit/test_paper_index_builder.py
tests/integration/test_real_paper_corpus_loader.py
tests/integration/test_real_corpus_search_providers.py
tests/integration/test_real_corpus_visual_retrieval.py
tests/integration/test_real_corpus_requested_count_10.py
tests/integration/test_real_corpus_language_control.py
tests/integration/test_real_corpus_insufficient_info.py
tests/integration/test_paper_root_config.py
tests/integration/test_domain_metadata_is_present.py
```

## 8. Runtime boundaries that will not be changed

Will not change:

- `AgenticRAGRuntime` remains a controlled bounded workflow.
- `AnswerWriter` will still only receive `EvidencePack`, never raw chunks.
- Providers will only read processed corpus/indexes, not parse PDFs.
- No web search provider will be added.
- No MCP, memory, production queue, eval runner, or RL implementation will be added.
- No query-time VLM/OCR/ColPali will be added.
- Fixtures will not be deleted or moved.
- User original source-drop files, if present later, will not be deleted or moved.

