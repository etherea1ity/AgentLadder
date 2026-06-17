# Chapter 3 Architecture: Agentic RAG Controlled Runtime

Chapter: `v0.3-agentic-rag`  
Title: **Klara's Controlled Research Runtime**  
Subtitle: **From Fixed Retrieval to Controlled Evidence Search**

This is the Phase B architecture artifact. It turns the discovery report into concrete code boundaries, contracts, nodes, files, tests, and non-goals.

## 1. Chapter Goal

Chapter 3 upgrades Chapter 2 from fixed retrieve-and-answer RAG to a local, bounded, evidence-search workflow:

```text
User request
→ normalize request / language / output requirements
→ route
→ split or classify sub-questions
→ plan evidence search
→ execute multi-path local paper search
→ fuse / dedup / diversity rerank
→ fetch selected evidence
→ build EvidencePack
→ write answer from EvidencePack only
→ verify citations, claims, visual evidence, language
→ final / revise once / insufficient_info
→ DecisionTrace + JSONL trace + Run Margin modules
```

The purpose is not to build a free autonomous research agent. The purpose is to teach the runtime architecture that makes later memory, web research, tools, eval, and RL possible.

## 2. Non-goals

Chapter 3 must not implement:

- Live Web Search or web page crawling.
- MCP server/client runtime.
- Long-term memory read/writeback.
- Production queues, auth, rate limiting, or distributed workers.
- Real RL or reward-model training.
- Full autonomous multi-agent teams.
- PDF download, OCR, cleaning, or parsing pipeline inside the runtime.
- Query-time VLM, OCR, ColPali/page-as-image retrieval.
- Huge `utils.py`, `common.py`, or `helpers.py` catch-all modules.
- Infinite or model-owned agent loops.

## 3. Boundaries With Later Chapters

| Chapter | Boundary |
| --- | --- |
| Chapter 4 Memory | Chapter 3 may preserve `DecisionRecord` and `EvidencePack` for later memory, but does not read/write user memory. |
| Chapter 5 Web Research | Chapter 3 defines `SearchProvider`/`FetchProvider`; implementations are local-paper only. Web providers come later. |
| Chapter 6 MCP | Chapter 3 capability specs are local registries only. No MCP transport, permission prompts, or external side-effect tools. |
| Chapter 7 Production | Chapter 3 is local, synchronous-ish, and JSONL based. No queues, workers, durable DB, auth, tenant isolation. |
| Chapter 8 Eval | Chapter 3 records decision/evidence/verification data but does not build a full eval flywheel. |
| Chapter 9 RL | Chapter 3 creates state/action/outcome traces that RL could consume later, but no training or policy optimization. |

## 4. Package Layout

Add small focused modules under existing layers:

```text
src/agent_ladder/
  rag/
    contracts/
      source.py                 # extend SourceCard only, backwards-compatible
      agentic.py                # RequestSpec, plans, evidence, AnswerFrameV2, workflow contracts
    agentic/
      __init__.py
      budget.py                 # BudgetManager
      failure.py                # FailurePolicyHandler
      registry.py               # CapabilityRegistry, WorkerAgentRegistry, SearchProviderRegistry
      runner.py                 # WorkerAgentRunner, NodeRunner
      trace.py                  # DecisionTracer
      normalizer.py             # request_normalizer, language controller, requirement parser
      planner.py                # evidence_search_planner, query_rewriter
      retrieval.py              # MultiPathRetriever, RRF, dedup, diversity rerank, grading
      evidence.py               # EvidenceReader, EvidenceSelector, EvidencePack builder
      writer.py                 # AnswerWriter constrained to EvidencePack
      verifier.py               # Citation/Evidence/Visual/Language verifiers
      runtime.py                # AgenticRAGRuntime skeleton + workflow nodes
      providers.py              # SearchProvider/FetchProvider protocols and local providers
  knowledge/
    paper/
      paper_card.py             # current PaperCard; may extend if needed
      corpus.py                 # PaperCorpus, PaperLoader, Fixture loader
      visuals.py                # VisualAssetStore, VisualElement loader helpers
      source_card.py            # PaperSourceCardBuilder
  app/cli/main.py               # add ask-agentic command, keep ask unchanged

data/papers/
  manifest.jsonl
  fixtures/
    <paper_id>/metadata.json
    <paper_id>/overview.md
    <paper_id>/chunks.jsonl
    <paper_id>/visuals.jsonl
    <paper_id>/figures/...
    <paper_id>/tables/...
```

No single module should become a junk drawer. Each file owns one architectural layer.

## 5. Contracts List

All new contracts are Pydantic and JSON serializable/deserializable.

### Request and routing contracts

- `RequestSpec`: normalized request identity, original query, language plan, requirements.
- `LanguagePlan`: input language, canonical query language, output language, explicitness.
- `OutputStyleSpec`: `short`, `explanatory`, `paper_list`, `comparison`, `research_brief`.
- `AnswerRequirement`: requested count, diversity/recent/method/limitation flags.
- `RouteState`: `direct`, `rag`, `mixed`, `insufficient_info` compatible route state.
- `SubQuestion`: bounded sub-question with canonical English query.

### Capability and worker contracts

- `CapabilitySpec`: capability id, kind, input/output schema names, budget tags.
- `WorkerAgentSpec`: one-shot worker id, input/output schema names, prompt label.
- `SearchProviderSpec`: provider id, search/fetch support, source types, filters.

### Search/fetch contracts

- `SearchRequest`, `SearchHit`, `FetchRequest`, `FetchResult`.
- `SearchUnit`: one planned path (`paper_overview_bm25`, `paper_chunk_dense`, etc.).
- `EvidenceSearchPlan`: canonical query, units, budgets, fusion, diversity, stop conditions.
- `RetrievalAttempt`: traceable result of a search/fetch/rewrite attempt.

### Paper/visual/evidence contracts

- `PaperCard`: paper metadata view for answer/source display.
- `VisualElement`: figure/table/page metadata from `visuals.jsonl`.
- `EvidenceItem`: supports `text`, `visual`, and `mixed` evidence.
- `EvidencePack`: writer-safe bundle; no raw unselected chunks.

### Answer/verification/runtime contracts

- `AnswerFrameV2`: final answer frame with mode, sub-questions, claims, evidence, citations, visual/rendered assets, final text.
- `VerificationResult`: citation/claim/language/visual support status.
- `DecisionRecord`: decision trace row.
- `BudgetState`: planned/used/clamped budgets.
- `FailurePolicy`: retry caps.
- `WorkflowState`: runtime-owned state across nodes.

## 6. Layering

```text
apps/web
  Display existing chat, module cards, run trace; optional visual thumbnails from trace payload.

apps/api
  Own sessions/messages/runs/SSE. Invoke Chapter 3 runtime for agentic runs. Do not own retrieval algorithms.

src/agent_ladder/app/cli
  CLI entry points: `ask` and `ask-agentic`.

src/agent_ladder/core
  Generic AskState, AnswerState, RunLog, token usage, JSONL trace. No Chapter 3 orchestration.

src/agent_ladder/llm
  Provider-neutral model interface. Workers call through WorkerAgentRunner.

src/agent_ladder/rag/contracts
  v0.2 and v0.3 RAG contracts.

src/agent_ladder/rag/agentic
  Controlled runtime, nodes, planner, retrieval, evidence, writer, verifier, registries.

src/agent_ladder/knowledge/paper
  Local paper corpus interface and visual asset store.

src/agent_ladder/infra
  Config loader and environment defaults.
```

## 7. Capability Registry Design

`CapabilityRegistry` stores what the runtime may do:

```text
capability_id: paper_chunk_bm25
kind: search_provider
input_schema: SearchRequest
output_schema: list[SearchHit]
budget_tags: [candidate_chunk_budget]
source_types: [paper_chunk]
```

The registry is not a tool marketplace. It is a local map used by `AgenticRAGRuntime` and tests to prove that only registered capabilities can be invoked.

## 8. Worker Agent Design

Workers are controlled, one-shot functions:

| Worker | Input | Output | Notes |
| --- | --- | --- | --- |
| `request_normalizer` | raw question | `RequestSpec` | May be rule-based first. |
| `evidence_search_planner` | `RequestSpec` | `EvidenceSearchPlan` | Runtime clamps budgets after planning. |
| `query_rewriter` | weak retrieval state | `EvidenceSearchPlan` or canonical query update | Max once. |
| `evidence_reader` | fetched results | candidate `EvidenceItem`s | No final writing. |
| `answer_writer` | `EvidencePack` | `AnswerFrameV2` | Cannot access raw chunks. |
| `answer_verifier` | `AnswerFrameV2` + `EvidencePack` | `VerificationResult` | Blocks bad citations/unsupported claims. |

`WorkerAgentRunner` responsibilities:

1. Validate input schema before call.
2. Invoke worker once.
3. Validate output schema after call.
4. Measure latency.
5. Record `DecisionRecord` and module payload.
6. Never allow worker-controlled loops.

## 9. Search/Fetch Provider Design

Provider protocol:

```text
SearchProvider.search(SearchRequest) -> list[SearchHit]
FetchProvider.fetch(FetchRequest) -> FetchResult
```

Local Chapter 3 providers:

- `paper_overview_dense`
- `paper_overview_bm25`
- `paper_metadata`
- `paper_chunk_dense`
- `paper_chunk_bm25`
- `paper_visual_caption`
- `paper_fetch`

`paper_fetch` fetches overview, chunk, or visual by stable ids. Search and fetch remain separate so Chapter 5 can add web search/read without changing planner/retriever/verifier contracts.

## 10. Figure-aware RAG Design

Standard visual metadata row:

```json
{
  "visual_id": "vis_selfrag_table_1",
  "paper_id": "paper_self_rag_fixture",
  "visual_type": "table",
  "label": "Table 1",
  "caption": "Retrieval and critique tokens improve factuality.",
  "page": 5,
  "image_path": "tables/table1.txt",
  "nearby_text": "...",
  "visual_summary": "A comparison table of baselines and Self-RAG."
}
```

Runtime behavior:

- Search captions/nearby text/visual summaries with BM25-style scoring.
- Fetch visual metadata and relative asset path.
- Convert visual result to `EvidenceItem(evidence_type="visual")`.
- Add visual source card with `source_type="paper_figure"` or `paper_table`.
- Include `visual_sources` / `rendered_assets` in `AnswerFrameV2`.

No query-time OCR or VLM. Those are lab notes only.

## 11. Latency Budget

Default teaching-mode budgets:

| Budget | Default | Clamp |
| --- | ---: | ---: |
| `search_units` | 3-5 | max 6 |
| requested output count | inferred or 5 | max 20 |
| `candidate_source_budget` | requested_count * 5 | max 60 |
| `candidate_chunk_budget` | requested_count * 8 | max 120 |
| `evidence_item_budget` | requested_count * 2 or 8 | max 24 |
| JSON repair | 0 used | max 1 |
| query rewrite | 0 used | max 1 |
| search expansion | 0 used | max 1 |
| answer revision | 0 used | max 1 |

Important rule: requested output count is not the same as retrieval top-k. “Give me 10 papers” means collect roughly 40-60 candidates, dedup/rerank, then output 10.

## 12. Failure Policy

`FailurePolicy` blocks uncontrolled retries:

- JSON repair max once.
- Query rewrite max once.
- Search expansion max once.
- Answer revision max once.
- Empty/weak retrieval after retry returns `insufficient_info`.
- Citation to nonexistent source blocks final.
- Unsupported claim triggers one revision; if still unsupported, remove claim or return partial/insufficient.
- Output-language mismatch reruns renderer only, not retrieval.

## 13. Trace Schema

`schema_version: v0.3` trace adds:

```json
{
  "workflow_state": { "run_mode": "agentic_rag", "route": "rag" },
  "request_spec": {},
  "search_plan": {},
  "retrieval_attempts": [],
  "evidence_pack": {},
  "answer_frame": {},
  "verification": {},
  "decisions": [],
  "modules": []
}
```

Every significant choice becomes a `DecisionRecord`:

- language/output decision
- route decision
- budget clamp
- search plan creation
- search provider attempt
- fusion/dedup/rerank decision
- query rewrite or expansion
- evidence selection
- citation verification
- claim revision/fallback

## 14. Workflow Nodes

Concrete node names:

1. `normalize_request`
2. `route_request`
3. `split_question`
4. `plan_evidence_search`
5. `execute_search`
6. `fuse_rerank`
7. `grade_retrieval`
8. `rewrite_query_if_needed`
9. `fetch_evidence`
10. `read_evidence`
11. `build_evidence_pack`
12. `write_answer`
13. `verify_answer`
14. `revise_or_final`

`NodeRunner` executes nodes sequentially from runtime-owned transition logic. Parallel search can happen inside `execute_search`, but each search path still records an attempt.

## 15. Tests

Unit tests required:

- `tests/unit/test_request_spec.py`
- `tests/unit/test_language_plan.py`
- `tests/unit/test_answer_requirement.py`
- `tests/unit/test_search_plan.py`
- `tests/unit/test_capability_registry.py`
- `tests/unit/test_worker_agent_registry.py`
- `tests/unit/test_paper_corpus_loader.py`
- `tests/unit/test_visual_element.py`
- `tests/unit/test_evidence_pack.py`
- `tests/unit/test_verifier.py`
- `tests/unit/test_budget_manager.py`
- `tests/unit/test_failure_policy.py`

Integration tests required:

- `tests/integration/test_agentic_rag_standard.py`
- `tests/integration/test_requested_count_10.py`
- `tests/integration/test_visual_retrieval.py`
- `tests/integration/test_language_control.py`
- `tests/integration/test_weak_retrieval_retry.py`
- `tests/integration/test_insufficient_info.py`
- `tests/integration/test_writer_cannot_access_raw_chunks.py`
- `tests/integration/test_trace_contains_decisions.py`

The repo may keep tests flat if desired, but names should make Chapter 3 coverage obvious.

## 16. CLI Contract

Command:

```bash
python -m agent_ladder.app.cli.main ask-agentic "给我 10 篇 Agentic RAG 相关论文，并按路线分类"
```

Output includes:

```text
Question:
...

Answer:
...

Sources:
...

Visual Sources:
...

Run info:
route=rag
run_mode=agentic_rag
search_units=...
retrieval_attempts=...
evidence_items=...
verification_status=...
latency_ms=...
trace_saved=True/False
```

Existing `ask` must remain unchanged.

## 17. Frontend Display Logic

Initial Chapter 3 implementation can reuse v0.2 Run Margin behavior:

- Emit module cards with existing `module_started`, `module_completed`, `module_failed` event types.
- Use public labels: normalize, plan, search, read, write, verify.
- Include visual evidence in module payload and trace; frontend may display it later.
- Do not expose raw chunks or chain-of-thought.
- Optional later UI enhancement: show visual thumbnails when `rendered_assets[].image_path` exists.
