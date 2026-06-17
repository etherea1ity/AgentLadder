# Chapter 3 Discovery Report: Agentic RAG

Chapter 3 target branch: `v0.3-agentic-rag`  
Working title: **Klara's Controlled Research Runtime**  
Subtitle: **From Fixed Retrieval to Controlled Evidence Search**

This report is the Phase A discovery artifact. It audits the current v0.1/v0.2 implementation and extracts architecture lessons from current agent/RAG runtimes before any Chapter 3 code is added.

## 1. Current Repository Audit

### 1.1 Chapter 1 reusable core

Chapter 1 already provides the minimal observable run harness:

| Concept | Current file | Reuse in Chapter 3 |
| --- | --- | --- |
| `AskState` | `src/agent_ladder/core/contracts/ask.py` | Keep as the base user-input state. Chapter 3 should wrap it in `RequestSpec`, not replace it. |
| `AnswerState` | `src/agent_ladder/core/contracts/answer.py` | Keep as the public text answer state. Chapter 3 should add `AnswerFrameV2` beside it. |
| `RunLog` / token usage | `src/agent_ladder/core/contracts/run.py`, `src/agent_ladder/core/contracts/usage.py` | Keep as run-level observability. Add workflow-level `BudgetState` and decision trace records separately. |
| JSONL trace | `src/agent_ladder/core/tracing/jsonl_tracer.py` | Reuse append-only JSONL storage. Extend payload schema to `v0.3`, do not break `v0.1`/`v0.2` readers. |
| LLM provider boundary | `src/agent_ladder/llm/base.py`, `src/agent_ladder/llm/providers/dashscope.py` | Reuse `BaseLLMClient`; Chapter 3 worker agents can call it through a controlled runner. |
| Config loading | `src/agent_ladder/infra/config/loader.py`, `configs/default.yaml`, `configs/models.yaml` | Reuse for model/runtime defaults. Add Chapter 3 budgets as explicit runtime defaults, not global hidden constants. |
| CLI entry | `src/agent_ladder/app/cli/main.py` | Add `ask-agentic` without changing existing `ask`. |

Chapter 1's lesson is still valid: a useful agent is not a raw model call; it is model + harness + state + trace.

### 1.2 Chapter 2 RAG assets that should be reused

Chapter 2 already implements a fixed local RAG chain:

```text
Question
→ Intent Router
→ Dense Retrieval + BM25
→ Hybrid Retrieval
→ Reranking
→ Context Builder
→ Klara Writer
→ AnswerFrameV1
→ Run Chain / JSONL Trace
```

Reusable components:

| Concept | Current file | Reuse / extension |
| --- | --- | --- |
| `Document`, `DocumentMetadata` | `src/agent_ladder/rag/contracts/document.py` | Reuse for markdown knowledge; add paper-specific contracts in `knowledge/paper`, not by bloating `Document`. |
| `TextChunk` | `src/agent_ladder/rag/contracts/chunk.py` | Reuse as text evidence source; paper chunks can map into chunk-like search/fetch results. |
| `IndexRecord` | `src/agent_ladder/rag/indexing/index_record.py` | Reuse for simple dense provider where possible. |
| `DenseRetriever` | `src/agent_ladder/rag/retrieval/dense.py` | Reuse for `paper_chunk_dense` mock/simple provider when vectors exist. |
| `BM25Retriever` | `src/agent_ladder/rag/retrieval/bm25.py` | Reuse scoring logic for paper overview/chunk BM25 providers. |
| `HybridRetriever` | `src/agent_ladder/rag/retrieval/hybrid.py` | Keep for v0.2; Chapter 3 should implement RRF multi-path fusion separately. |
| `SimpleReranker` | `src/agent_ladder/rag/reranking/simple_reranker.py` | Reuse signals; add diversity reranker at paper level. |
| `SourceCard`, `Citation` | `src/agent_ladder/rag/contracts/source.py` | Extend in a backwards-compatible way for `paper_chunk`, `paper_figure`, `paper_table`, `paper_visual`. |
| `AnswerFrameV1`, v0.2 `EvidenceItem` | `src/agent_ladder/rag/contracts/answer_frame.py` | Keep as v0.2. Add `AnswerFrameV2` and richer Chapter 3 evidence contracts in new files. |
| Module cards | `src/agent_ladder/rag/contracts/module.py`, `apps/api/services/run_service.py` | Reuse public Run Margin card shape. New runtime nodes should emit `ModuleResult`-compatible summaries. |
| API/SSE display logic | `apps/api/services/run_service.py`, `apps/web/src/types/domain.ts`, `apps/web/src/components/RunMargin.tsx` | Preserve event names; add payloads/modules rather than forcing frontend rewrites. |

### 1.3 Current constraints and risks

- `KlaraAgent` currently lives under `src/agent_ladder/core/runtime/klara_agent.py`. The v0.2 freeze explicitly marks this as acceptable only for the small fixed RAG chain. Chapter 3 should move agentic orchestration into a RAG/runtime boundary such as `src/agent_ladder/rag/agentic/` while keeping `core` generic.
- The current `JsonlAppStore.delete_session()` hard-deletes local app/trace records, while the v0.1 skill text originally mentions append-only tombstones. Chapter 3 should not alter delete behavior unless a separate product decision is made.
- The frontend already understands public run phases and module cards, including conceptual `KlaraVisualPhase` values like `searching`, `reading`, `checking`, and `writing`. Chapter 3 can map controlled workflow nodes to existing module events first; richer UI is optional.
- Existing examples/tests for Chapter 1/2 must continue: `python -m agent_ladder.app.cli.main ask ...`, `scripts/rag/build_index.py`, API run creation, SSE streaming, and v0.2 RAG routing.

## 2. External Architecture Research

### 2.1 OpenAI Agents SDK

Official docs describe agents as LLMs configured with instructions, tools, handoffs, guardrails, and structured outputs, with the SDK runner managing orchestration when the developer chooses that abstraction. The docs also distinguish owning the loop directly via lower-level APIs when the application needs control. OpenAI Agents tracing records LLM generations, tool calls, handoffs, guardrails, and custom events as spans within a workflow trace. Handoffs expose delegation as model-visible tools, and input schemas can be Pydantic models that are validated before being passed into callbacks.

Implication for Agent Ladder: Chapter 3 should teach **server/runtime-owned orchestration** and **typed worker contracts**. We should not let the writer or planner free-call arbitrary tools. The runtime should invoke bounded workers, validate input/output schemas, and record each decision as traceable data.

Sources: OpenAI Agents SDK Agents, Handoffs, Tools, Guardrails, and Tracing docs:  
- https://openai.github.io/openai-agents-python/agents/  
- https://openai.github.io/openai-agents-python/handoffs/  
- https://openai.github.io/openai-agents-python/tools/  
- https://openai.github.io/openai-agents-python/guardrails/  
- https://openai.github.io/openai-agents-python/tracing/

### 2.2 Claude Code / Claude Code SDK

Anthropic's Claude Code documentation emphasizes terminal/workspace execution, hierarchical project/user settings, tool permissions, hooks, and project/user subagents. The SDK permission docs describe complementary controls: permission modes, `canUseTool`, hooks, and declarative allow/deny/ask rules, with hooks able to run before/after tool use. Settings also allow hiding sensitive files through deny rules.

Implication for Agent Ladder: Chapter 3's local research runtime should separate **capability registration** from **permission and budget policy**. Even though Chapter 3 is not an MCP/tool chapter, it should already model capabilities with explicit ids, input/output schemas, provider names, and failure policies. This prepares Chapter 6 without exposing unlimited tool execution now.

Sources:  
- https://docs.anthropic.com/en/docs/claude-code/overview  
- https://docs.anthropic.com/en/docs/claude-code/settings  
- https://docs.anthropic.com/en/docs/claude-code/sdk/sdk-permissions  
- https://docs.anthropic.com/en/docs/claude-code/sub-agents  
- https://docs.anthropic.com/en/docs/claude-code/hooks

### 2.3 OpenClaw

OpenClaw positions itself as a self-hosted gateway that connects chat/channel surfaces to agent runtimes. Its docs describe a single embedded runtime per gateway with its own workspace, bootstrap files, session store, and skill roots at user/workspace levels. Skills can be managed with allowlists and per-agent configuration.

Implication for Agent Ladder: Chapter 3 should not copy OpenClaw's broad personal-agent gateway scope. The useful lesson is the **workspace/capability boundary**: a runtime owns which capabilities are available and how they are resolved. Agent Ladder should implement a small local `CapabilityRegistry`, `WorkerAgentRegistry`, and `SearchProviderRegistry`, not a channel gateway.

Sources:  
- https://docs.openclaw.ai/  
- https://docs.openclaw.ai/agent  
- https://docs.openclaw.ai/skills-config

### 2.4 LangGraph

LangGraph's docs frame the runtime as a low-level orchestration layer for long-running, stateful workflows. It emphasizes state graphs, nodes as functions, durable execution, checkpoints at step boundaries, deterministic replay, idempotent side effects, retries, and human-in-the-loop state inspection. Its “Thinking in LangGraph” guidance says to break workflows into discrete steps, store raw state, treat errors as part of the flow, and inspect state between nodes.

Implication for Agent Ladder: Chapter 3 should use a simple local state-machine skeleton: named nodes, typed `WorkflowState`, explicit transitions, budget/failure policy, and JSONL trace. It does not need to adopt LangGraph as a dependency; the chapter should teach the architectural idea in small code.

Sources:  
- https://docs.langchain.com/oss/python/langgraph  
- https://docs.langchain.com/oss/python/langgraph/graph-api  
- https://docs.langchain.com/oss/python/langgraph/durable-execution  
- https://docs.langchain.com/oss/python/langgraph/persistence  
- https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph

### 2.5 LlamaIndex and Haystack Agentic RAG patterns

LlamaIndex demonstrates `QueryFusionRetriever`, where multiple generated queries and multiple retrievers can be fused, including reciprocal-rank fusion. Its API reference shows the standard RRF formula using a rank constant such as `k=60`. Haystack documents pipeline composition where BM25 and embedding retrievers feed a `DocumentJoiner`, and hybrid retrievers combine keyword and embedding search strengths.

Implication for Agent Ladder: Chapter 3 should upgrade from v0.2's fixed dense+BM25 weighted fusion to **planned multi-path search**: overview search, metadata search, chunk search, and visual caption search can all return the same `SearchHit` contract and be fused/deduped/reranked at paper level.

Sources:  
- https://docs.llamaindex.ai/en/stable/examples/retrievers/reciprocal_rerank_fusion/  
- https://docs.llamaindex.ai/en/stable/api_reference/retrievers/query_fusion/  
- https://docs.haystack.deepset.ai/docs/documentjoiner  
- https://docs.haystack.deepset.ai/docs/opensearchhybridretriever  
- https://docs.haystack.deepset.ai/v2.2/docs/multiplexer

## 3. What Chapter 2 Can Reuse

Chapter 3 should reuse these Chapter 2 pieces directly:

1. Existing `Document`, `TextChunk`, `IndexRecord`, local JSONL storage, BM25 tokenizer/scorer, simple vector index, dense retriever, and DashScope embedder.
2. Existing `SourceCard` and `Citation` as public source/citation vocabulary, extended only with optional fields.
3. Existing `ModuleResult` cards and SSE event stream so frontend Run Margin remains stable.
4. Existing `BaseLLMClient` and streaming writer path for final answer generation.
5. Existing `JsonlTracer` file path and append behavior with a new `schema_version: v0.3` trace payload.
6. Existing v0.2 fixed RAG path as a fallback and regression anchor.

## 4. What Chapter 3 Should Extend

Chapter 3 should add:

- `RequestSpec`, language/output/requirement contracts to normalize user intent.
- `EvidenceSearchPlan` with search units, budgets, diversity requirements, and stop conditions.
- Search/fetch provider abstraction for local papers (`SearchRequest` → `SearchHit`, `FetchRequest` → `FetchResult`).
- Paper corpus interface under `data/papers/`, including overviews, chunks, visual metadata, figures/tables/pages paths.
- Multi-path search, RRF fusion, paper-level dedup, diversity reranking, and controlled retry/rewrite once.
- EvidencePack boundary: writer sees only selected evidence, not raw chunks.
- Verification step with citation/source existence, claim support, visual evidence, and output-language checks.
- DecisionTrace: every route, rewrite, budget clamp, search expansion, evidence selection, verification result, and final fallback decision becomes a `DecisionRecord`.

## 5. What Belongs to Later Chapters

Do **not** implement these in Chapter 3:

| Future chapter | Not now |
| --- | --- |
| Chapter 4 Memory | Long-term memory, conversational memory policies, profile memory, memory retrieval/writeback. |
| Chapter 5 Web Research | Live web search, page crawling, web fetch, robots/allowlist policy, external source freshness. |
| Chapter 6 MCP Tool Agent | MCP server/client runtime, broad tool execution, permission prompts, external side-effect tools. |
| Chapter 7 Production Agent | Queues, background worker fleet, durable DB migrations, auth, rate limiting, production deployment. |
| Chapter 8 Eval Data Flywheel | Full evaluator dashboards, golden dataset generation, offline metrics pipeline. |
| Chapter 9 RL for Agent | Real reinforcement learning, policy optimization, reward model training. |
| Labs only | OCR, query-time VLM, ColPali/page-as-image retrieval, PDF download/cleaning pipeline. |

## 6. Why Controlled Runtime Instead of a Free Agent Loop

A free loop is attractive because it can let the model decide what to do next. It is wrong for Chapter 3 because Agent Ladder is teaching architecture stability, not maximum autonomy.

Controlled runtime benefits:

1. **Bounded cost**: budgets can clamp top-k, candidate counts, retry counts, and evidence item counts.
2. **Typed safety**: workers return Pydantic contracts that the runtime validates before state transitions.
3. **Traceability**: each node and decision has a stable event schema for UI, eval, and later RL.
4. **Failure policy**: JSON repair, rewrite, search expansion, and answer revision are each limited to once.
5. **Frontend stability**: a known workflow maps cleanly to Run Margin cards.
6. **Teaching clarity**: learners can see runtime-owned transitions instead of opaque model behavior.

The model still contributes intelligence: normalizing intent, rewriting queries, selecting evidence, writing, and verifying. But it never owns the loop.

## 7. Why Search/Fetch Abstraction

Search/fetch is the bridge from local RAG to future web research:

```text
SearchProvider.search(SearchRequest) -> list[SearchHit]
FetchProvider.fetch(FetchRequest) -> FetchResult
```

In Chapter 3, providers read local paper metadata, overviews, chunks, and visual captions. In Chapter 5, web search/read providers can implement the same shape. This means the runtime can learn planning, fusion, dedup, fetch, evidence packing, and verification once, without hardcoding “local chunks only”.

## 8. Why DecisionTrace

`DecisionRecord` is required because later chapters need supervised data from real runs:

- Eval needs to score route decisions, rewrite decisions, retrieval attempts, evidence selection, citation checks, and insufficient-evidence decisions.
- RL needs state/action/outcome records, not just final answer text.
- Debugging needs to explain why a query was expanded, why a budget was clamped, why a claim was removed, or why a result was marked insufficient.

`DecisionRecord` should include `decision_id`, `node_name`, `decision_type`, inputs/outputs summary, alternatives considered when available, reason, confidence, latency, and errors.

## 9. Why Figure-aware RAG

Paper understanding is not only text. Figures and tables often encode architectures, ablations, benchmark comparisons, and conceptual diagrams. If Chapter 3 supports a local paper library but ignores figure/table metadata, it teaches an incomplete research workflow.

The Chapter 3 boundary should be deliberately modest:

- Load `visuals.jsonl` metadata.
- Search captions, nearby text, and `visual_summary`.
- Return visual `EvidenceItem`s and `SourceCard`s.
- Show image path/caption/page in CLI and optionally thumbnail in web UI.

It should not perform query-time OCR, VLM reading, or ColPali-style page image retrieval. Those belong in `docs/labs/ch03-multimodal-rag-labs.md`.

## 10. Phase A Implementation Handoff

The safe next step is Phase B: write a concrete architecture and chapter boundary doc that maps the Chapter 3 controlled runtime to files, classes, workflow nodes, tests, CLI command, and UI trace display. Implementation should not begin until the architecture artifact exists.
