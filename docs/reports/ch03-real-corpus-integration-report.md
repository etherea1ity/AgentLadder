# Chapter 3 Real Paper Corpus Integration Report

## 1. What changed

Connected the existing local processed paper corpus under `data/papers` to Chapter 3 Agentic RAG without changing the controlled runtime principles.

Implemented:

- Local paper source-drop audit script.
- Repeatable corpus migration/normalization script.
- Strict corpus validator.
- Deterministic lightweight paper index builder.
- Real-corpus smoke runner.
- `ask-agentic --paper-root data/papers` CLI path.
- Domain-aware metadata for paper text and paper visual evidence.
- Real corpus tests for loader, search providers, visual retrieval, requested count, language control, insufficient info, and paper-root config.

The original `data/papers/fixtures` remains intact and remains the default test corpus.

## 2. Files added/modified

Major added/updated files:

```text
docs/architecture/ch03-paper-corpus-audit-plan.md
docs/architecture/ch03-domain-aware-local-rag.md
docs/architecture/ch03-paper-data-versioning-policy.md
docs/reports/ch03-real-corpus-integration-report.md

scripts/ingest/audit_local_paper_drop.py
scripts/ingest/build_paper_corpus.py
scripts/ingest/validate_paper_corpus.py
scripts/index/build_paper_indexes.py
scripts/dev/run_ch03_real_corpus_smoke.py

src/agent_ladder/knowledge/paper/corpus.py
src/agent_ladder/knowledge/paper/ids.py
src/agent_ladder/knowledge/paper/schema.py
src/agent_ladder/knowledge/paper/validation.py
src/agent_ladder/knowledge/paper/migration.py
src/agent_ladder/knowledge/paper/indexing.py
src/agent_ladder/knowledge/paper/visuals.py

src/agent_ladder/rag/contracts/agentic.py
src/agent_ladder/rag/contracts/source.py
src/agent_ladder/rag/agentic/runtime.py
src/agent_ladder/rag/agentic/providers.py
src/agent_ladder/rag/agentic/retrieval.py
src/agent_ladder/rag/agentic/evidence.py
src/agent_ladder/rag/agentic/writer.py
src/agent_ladder/rag/agentic/verifier.py
src/agent_ladder/rag/agentic/planner.py
src/agent_ladder/rag/agentic/normalizer.py
src/agent_ladder/app/cli/main.py

.tests/unit and tests/integration Chapter 3 real-corpus tests
```

Generated corpus outputs:

```text
data/papers/manifest.jsonl
data/papers/processed/<paper_id>/metadata.json
data/papers/processed/<paper_id>/overview.md
data/papers/processed/<paper_id>/chunks.jsonl
data/papers/processed/<paper_id>/visuals.jsonl
data/papers/indexes/paper_overview_index.json
data/papers/indexes/paper_chunk_index.json
data/papers/indexes/paper_metadata_index.json
data/papers/indexes/paper_visual_caption_index.json
data/papers/quality_reports/source_audit.json
data/papers/quality_reports/source_audit_report.md
data/papers/quality_reports/migration_report.md
data/papers/quality_reports/corpus_report.md
data/papers/quality_reports/validation_report.md
data/papers/quality_reports/integration_report.md
```

## 3. Corpus statistics

Current real corpus statistics after normalization:

```text
total_manifest_count: 40
processed_count: 40
partial_count: 0
failed_count: 0
chunk_count_total: 10559
visual_count_total: 959
papers_with_figures: 36
papers_with_tables: 40
missing_field_statistics: none
duplicate_title_warnings: none
access_status_distribution: open_access=40
```

Important audit finding:

```text
data/papers/论文 does not exist in the current workspace snapshot.
```

Therefore the task normalized the already existing real corpus in:

```text
data/papers/processed
data/papers/raw
data/papers/manifest.jsonl
```

No source-drop/original files were deleted.

## 4. Validation results

Command run:

```bash
.venv/bin/python scripts/ingest/validate_paper_corpus.py --root data/papers --strict
```

Result:

```text
validation_status=passed
errors=0
warnings=0
```

Report:

```text
data/papers/quality_reports/validation_report.md
```

## 5. Integration smoke results

Command run:

```bash
.venv/bin/python scripts/dev/run_ch03_real_corpus_smoke.py
```

Result: passed.

Smoke queries covered:

1. `给我 10 篇 Agentic RAG 相关论文，并按路线分类`
2. `Explain Self-RAG in Chinese.`
3. `Compare ReAct, Reflexion, and Voyager.`
4. `Find papers about retrieval control and query rewriting.`
5. `Explain figure-aware RAG in Chinese, include figure if available.`
6. `找几篇 world model / spatial world model 相关论文。`
7. `This query should not match anything: qwerty_nonexistent_agent_ladder_topic`

Observed important behavior:

- Requested count 10 uses candidate budget greater than final source count.
- Visual query calls `paper_visual_caption` and returns at least one caption-backed visual source when available.
- Nonexistent query returns zero sources and `evidence_status=insufficient`.
- Trace is saved for smoke queries.

Report:

```text
data/papers/quality_reports/integration_report.md
```

## 6. Test results

Commands run:

```bash
.venv/bin/python -m pytest tests/unit tests/integration -q
.venv/bin/python -m pytest -q
```

Results:

```text
tests/unit + tests/integration: 38 passed
full pytest suite: 50 passed, 2 warnings
```

Warnings are existing Pydantic datetime deprecation warnings in older tests.

## 7. Known limitations

1. The source-drop directory `data/papers/论文` is absent in this workspace snapshot; the real corpus was already present under `data/papers/processed`.
2. The current indexes are deterministic lightweight JSON indexes, not production embedding indexes.
3. Search still uses lightweight keyword scoring, not a production dense vector store.
4. Figure-aware RAG is metadata/caption based only.
5. No query-time OCR, VLM, ColPali, Web Search, MCP, Memory, Production Queue, or RL was added.
6. Some generated overviews remain auto-generated and should be manually improved for teaching quality.
7. `.venv/bin/python` was used because this WSL environment does not expose a plain `python` binary.

## 8. How to rebuild corpus

From repo root:

```bash
.venv/bin/python scripts/ingest/audit_local_paper_drop.py --input "data/papers/论文" --output data/papers/quality_reports/source_audit_report.md
.venv/bin/python scripts/ingest/build_paper_corpus.py --input "data/papers/论文" --root data/papers --mode migrate_existing
.venv/bin/python scripts/ingest/validate_paper_corpus.py --root data/papers --strict
.venv/bin/python scripts/index/build_paper_indexes.py --root data/papers
.venv/bin/python scripts/dev/run_ch03_real_corpus_smoke.py
```

On Windows, use the project venv/python launcher equivalent if needed.

## 9. How to run real corpus ask-agentic

```bash
.venv/bin/python -m agent_ladder.app.cli.main ask-agentic "给我 10 篇 Agentic RAG 相关论文，并按路线分类" --paper-root data/papers
```

Visual query:

```bash
.venv/bin/python -m agent_ladder.app.cli.main ask-agentic "Explain figure aware RAG in Chinese, include figure" --paper-root data/papers
```

Environment fallback also works:

```bash
AGENT_LADDER_PAPER_ROOT=data/papers .venv/bin/python -m agent_ladder.app.cli.main ask-agentic "Agentic RAG 是什么？"
```

## 10. Next recommended fixes

1. Improve the auto-generated `overview.md` files for the most important teaching papers.
2. Add a real embedding-backed index behind the existing provider abstraction, without changing runtime contracts.
3. Add a small frontend visual-source display card using existing Run Margin/module-card patterns.
4. Add better section-aware chunk role classification: `paper_method`, `paper_result`, and `paper_claim`.
5. Keep fixtures as CI-stable data and keep the real corpus as local/rebuildable data.
