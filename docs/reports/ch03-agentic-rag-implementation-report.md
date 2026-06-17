# Chapter 3 Implementation Report: Agentic RAG

**Project:** Agent Ladder  
**Chapter:** Chapter 3 — Agentic RAG / Klara's Controlled Research Runtime  
**Theme:** From Fixed Retrieval to Controlled Evidence Search  
**Status:** Implemented as a runnable local teaching/runtime version using fixture paper corpus.

---

## 1. What Was Built

Chapter 3 upgrades the previous fixed retrieve-and-answer RAG direction into a local, runtime-controlled Agentic RAG workflow.

The main architectural shift is:

> The LLM/worker does not control the loop. The runtime owns workflow transitions, budgets, failure policy, schema validation, trace, and finalization.

The implemented runtime supports:

1. Request normalization.
2. Language planning.
3. Answer requirement parsing.
4. Evidence search planning.
5. Multi-path local paper search.
6. RRF fusion.
7. Paper-level deduplication.
8. Diversity reranking.
9. Fetching paper text and visual metadata.
10. EvidencePack construction.
11. Answer writing from EvidencePack only.
12. Citation/evidence/language/visual verification.
13. Controlled retry/revision policy.
14. Decision trace and workflow trace output.
15. CLI execution through `ask-agentic`.

---

## 2. What Can Run Now

The Chapter 3 CLI can be run with:

```bash
python -m agent_ladder.app.cli.main ask-agentic "给我 10 篇 Agentic RAG 相关论文，并按路线分类"
```

It executes the local Agentic RAG runtime end-to-end and prints:

- Question
- Answer
- Sources
- Visual Sources, when present
- Run info
- Route
- Run mode
- Search unit count
- Retrieval attempt count
- Evidence item count
- Verification status
- Latency
- Trace saved status

A visual retrieval example can also run:

```bash
python -m agent_ladder.app.cli.main ask-agentic "Explain figure aware RAG in Chinese, include figure"
```

This can return visual source metadata such as:

- `image_path`
- `caption`
- `page`

---

## 3. Current Runtime Scope

The current implementation is a **local fixture-corpus teaching runtime**, not a production research platform.

It uses:

```text
data/papers/fixtures/
```

as the local paper corpus.

The fixture corpus contains three paper examples:

1. Agentic RAG direction.
2. World Model direction.
3. Figure/Table example.

At least one fixture includes a figure, and at least one includes a table.

---

## 4. What Was Not Built

The following were intentionally not implemented because they belong to later chapters or labs:

1. **No Web Search**
   - Chapter 3 only defines local `search/fetch` abstraction.
   - Future Web Research can implement another provider behind the same abstraction.

2. **No MCP Server**
   - MCP tool/runtime integration is reserved for a later chapter.

3. **No Long-term Memory**
   - Chapter 3 only uses per-run workflow state and trace.
   - Persistent memory belongs to Chapter 4.

4. **No Production Queue**
   - No job queue, distributed worker, rate limiter, or production orchestration.

5. **No Real RL**
   - DecisionRecord and trace are prepared for future Eval/RL usage, but no training loop exists.

6. **No Free Agent Loop**
   - Worker calls are one-shot and schema-bound.
   - Runtime controls transitions and retry limits.

7. **No Full Multi-agent Autonomous Team**
   - Chapter 3 has controlled worker contracts, not autonomous agent teams.

8. **No PDF Download / Cleaning Pipeline**
   - Paper processing is expected to be handled outside the Agentic RAG runtime.
   - The runtime reads standardized processed paper data.

9. **No Query-time VLM / OCR / ColPali**
   - Figure-aware RAG is caption/metadata based only.
   - Advanced multimodal retrieval is documented as a future lab direction.

10. **No Giant `utils.py` / `common.py` / `helpers.py`**
    - Code is split by runtime, contracts, providers, evidence, verifier, and knowledge boundaries.

---

## 5. Architecture Summary

Chapter 3 is organized around these layers:

```text
CLI / App Layer
    ↓
AgenticRAGRuntime
    ↓
Workflow Nodes
    ↓
Request Normalizer / Search Planner / Retriever / Evidence Builder / Writer / Verifier
    ↓
Search & Fetch Providers
    ↓
Paper Corpus / Visual Asset Store
    ↓
Contracts / Trace / Budget / Failure Policy
```

### 5.1 Runtime-owned Workflow

The central rule is:

> The runtime owns the workflow. Workers only return typed outputs.

Main runtime workflow:

```text
normalize_request
→ route_request
→ split_question
→ plan_evidence_search
→ execute_search
→ fuse_rerank
→ grade_retrieval
→ rewrite_query_if_needed
→ fetch_evidence
→ read_evidence
→ build_evidence_pack
→ write_answer
→ verify_answer
→ revise_or_final
```

### 5.2 Search / Fetch Abstraction

Chapter 3 introduces local search/fetch providers so that local RAG and future Web Research can share the same conceptual interface.

Current providers include:

- paper overview dense-style search
- paper overview BM25-style search
- paper metadata search
- paper chunk dense-style search
- paper chunk BM25-style search
- paper visual caption search
- paper fetch

### 5.3 EvidencePack Boundary

A hard boundary was added:

> AnswerWriter cannot read raw chunks. It only receives EvidencePack.

This prepares the project for:

- better citation discipline
- later eval data collection
- decision trace analysis
- future RL-style optimization

### 5.4 Figure-aware RAG

Chapter 3 supports figure/table/visual metadata through:

- `VisualElement`
- visual source cards
- visual `EvidenceItem`
- `visual_sources` / `rendered_assets` in `AnswerFrameV2`

It does not perform real-time visual model inference.

---

## 6. Key Contracts Added

The main new Pydantic contracts are in:

```text
src/agent_ladder/rag/contracts/agentic.py
```

Important contracts include:

- `RequestSpec`
- `LanguagePlan`
- `OutputStyleSpec`
- `AnswerRequirement`
- `RouteState`
- `SubQuestion`
- `CapabilitySpec`
- `WorkerAgentSpec`
- `SearchProviderSpec`
- `SearchRequest`
- `SearchHit`
- `FetchRequest`
- `FetchResult`
- `SearchUnit`
- `EvidenceSearchPlan`
- `RetrievalAttempt`
- `PaperCard`
- `VisualElement`
- `EvidenceItem`
- `EvidencePack`
- `AnswerFrameV2`
- `VerificationResult`
- `DecisionRecord`
- `BudgetState`
- `FailurePolicy`
- `WorkflowState`

The existing `SourceCard` was extended compatibly to support paper and visual source types without breaking old usage.

---

## 7. Main Files Added or Changed

### 7.1 Architecture / Docs

```text
docs/architecture/ch03-discovery-report.md
docs/architecture/ch03-agentic-rag-architecture.md
docs/chapters/ch03-agentic-rag.md
docs/labs/ch03-multimodal-rag-labs.md
docs/freezes/v0.3-agentic-rag-freeze.md
README.md
```

### 7.2 Contracts

```text
src/agent_ladder/rag/contracts/agentic.py
src/agent_ladder/rag/contracts/__init__.py
src/agent_ladder/rag/contracts/source.py
```

### 7.3 Runtime

```text
src/agent_ladder/rag/agentic/runtime.py
src/agent_ladder/rag/agentic/registry.py
src/agent_ladder/rag/agentic/runner.py
src/agent_ladder/rag/agentic/budget.py
src/agent_ladder/rag/agentic/failure.py
src/agent_ladder/rag/agentic/trace.py
src/agent_ladder/rag/agentic/normalizer.py
src/agent_ladder/rag/agentic/planner.py
src/agent_ladder/rag/agentic/providers.py
src/agent_ladder/rag/agentic/retrieval.py
src/agent_ladder/rag/agentic/evidence.py
src/agent_ladder/rag/agentic/writer.py
src/agent_ladder/rag/agentic/verifier.py
src/agent_ladder/rag/agentic/__init__.py
```

### 7.4 Paper Corpus / Knowledge Layer

```text
src/agent_ladder/knowledge/__init__.py
src/agent_ladder/knowledge/paper/__init__.py
src/agent_ladder/knowledge/paper/corpus.py
src/agent_ladder/knowledge/paper/visuals.py
src/agent_ladder/knowledge/paper/source_card.py
```

### 7.5 CLI

```text
src/agent_ladder/app/cli/main.py
```

Added command:

```text
ask-agentic
```

### 7.6 Fixture Corpus

```text
data/papers/manifest.jsonl
data/papers/fixtures/paper_agentic_rag/metadata.json
data/papers/fixtures/paper_agentic_rag/overview.md
data/papers/fixtures/paper_agentic_rag/chunks.jsonl
data/papers/fixtures/paper_agentic_rag/visuals.jsonl
data/papers/fixtures/paper_agentic_rag/tables/table1.txt

data/papers/fixtures/paper_world_model/metadata.json
data/papers/fixtures/paper_world_model/overview.md
data/papers/fixtures/paper_world_model/chunks.jsonl
data/papers/fixtures/paper_world_model/visuals.jsonl

data/papers/fixtures/paper_visual_transformer/metadata.json
data/papers/fixtures/paper_visual_transformer/overview.md
data/papers/fixtures/paper_visual_transformer/chunks.jsonl
data/papers/fixtures/paper_visual_transformer/visuals.jsonl
data/papers/fixtures/paper_visual_transformer/figures/figure1.txt
```

### 7.7 Examples

```text
examples/agentic_rag/ask_agentic_rag.py
examples/agentic_rag/ask_paper_list.py
examples/agentic_rag/ask_requested_count_10.py
examples/agentic_rag/ask_comparison.py
examples/agentic_rag/ask_visual_figure.py
examples/agentic_rag/ask_language_control.py
examples/agentic_rag/ask_weak_retrieval_retry.py
examples/agentic_rag/ask_insufficient_info.py
```

### 7.8 Tests

Unit tests:

```text
tests/unit/test_request_spec.py
tests/unit/test_language_plan.py
tests/unit/test_answer_requirement.py
tests/unit/test_search_plan.py
tests/unit/test_capability_registry.py
tests/unit/test_worker_agent_registry.py
tests/unit/test_paper_corpus_loader.py
tests/unit/test_visual_element.py
tests/unit/test_evidence_pack.py
tests/unit/test_verifier.py
tests/unit/test_budget_manager.py
tests/unit/test_failure_policy.py
```

Integration tests:

```text
tests/integration/test_agentic_rag_standard.py
tests/integration/test_requested_count_10.py
tests/integration/test_visual_retrieval.py
tests/integration/test_language_control.py
tests/integration/test_weak_retrieval_retry.py
tests/integration/test_insufficient_info.py
tests/integration/test_writer_cannot_access_raw_chunks.py
tests/integration/test_trace_contains_decisions.py
```

---

## 8. Verification

The following checks were run successfully:

```text
Python tests: 32 passed, 2 warnings
Frontend tests: 16 passed
Frontend build: passed
```

CLI examples were also exercised:

```bash
python -m agent_ladder.app.cli.main ask-agentic "给我 10 篇 Agentic RAG 相关论文，并按路线分类"
```

and:

```bash
python -m agent_ladder.app.cli.main ask-agentic "Explain figure aware RAG in Chinese, include figure"
```

Both ran through the Chapter 3 runtime.

---

## 9. Important Design Decisions

### 9.1 Controlled Runtime Instead of Free Agent Loop

A free loop would make teaching, tracing, testing, and later eval/RL harder. Chapter 3 therefore uses a bounded workflow with explicit nodes and retry limits.

### 9.2 Search/Fetch Abstraction

Local RAG and future Web Research should share the same shape:

```text
SearchRequest → SearchHit → FetchRequest → FetchResult
```

This lets Chapter 5 add web providers without rewriting the runtime architecture.

### 9.3 EvidencePack as Writer Boundary

The writer is not allowed to see raw chunks. This prevents hidden evidence use and makes citation verification more explicit.

### 9.4 DecisionRecord for Future Eval/RL

The runtime records key decisions so later chapters can convert traces into eval data and eventually RL-style feedback loops.

### 9.5 Figure-aware RAG as Metadata-first

Chapter 3 supports visual evidence through captions, summaries, nearby text, and asset paths. It deliberately avoids real-time VLM/OCR to keep the chapter focused and stable.

---

## 10. Known Limitations

1. Providers are simple/local implementations.
2. Dense search is teaching-grade, not production embedding infrastructure.
3. Corpus is fixture-based until a real processed paper corpus is supplied.
4. Figure retrieval is caption/metadata based only.
5. The web UI is not yet deeply integrated with Chapter 3 visual cards, though the data structures are ready.
6. Retrieval quality depends on fixture metadata and simple scoring.
7. No production persistence beyond JSONL/trace-style local artifacts.

---

## 11. Recommended Next Steps

1. Review `docs/architecture/ch03-agentic-rag-architecture.md` first.
2. Run the `ask-agentic` CLI command.
3. Review `src/agent_ladder/rag/agentic/runtime.py` as the main execution entry.
4. Review `src/agent_ladder/rag/contracts/agentic.py` for the contract surface.
5. Replace or extend `data/papers/fixtures` with a larger processed paper corpus later.
6. If desired, add frontend display integration for Chapter 3 visual sources using the existing Run Margin/module card pattern.

