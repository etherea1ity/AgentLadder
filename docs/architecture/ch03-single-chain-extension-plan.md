# Chapter 3 Single-Chain Extension Plan

## Target architecture

```text
Existing Chat UI
→ existing chat submit / ask request
→ /api/runs
→ RunService
→ unified v0.3 controlled local evidence runtime
→ AskState / RequestSpec
→ one EvidenceSearchPlan over source domains
   - project_docs
   - chapter_docs
   - paper_corpus
   - paper_visuals
→ Search / Fetch providers
→ EvidencePack
→ AnswerFrameV2
→ VerificationResult + DecisionTrace
→ same Chat UI renders assistant answer
→ Run Margin renders optional source/evidence/visual panels
```

There is no separate Chapter 3 app, no standalone RAG endpoint, and no mock answer path.

## Existing chain found

- Frontend shell: `apps/web/src/App.tsx`
- Chat UI: `apps/web/src/components/ChatWorkspace.tsx`
- Run margin / trace panel: `apps/web/src/components/RunMargin.tsx`
- API client: `apps/web/src/api/client.ts`
- Main backend route: `apps/api/routes/runs.py`
- Main backend service: `apps/api/services/run_service.py`
- Store/SSE: `apps/api/services/app_store.py`, `apps/api/services/sse_bus.py`

## v0.3 runtime files

- Runtime: `src/agent_ladder/rag/agentic/runtime.py`
- Contracts: `src/agent_ladder/rag/contracts/agentic.py`
- Normalizer: `src/agent_ladder/rag/agentic/normalizer.py`
- Planner: `src/agent_ladder/rag/agentic/planner.py`
- Providers: `src/agent_ladder/rag/agentic/providers.py`
- Retrieval/fusion/rerank: `src/agent_ladder/rag/agentic/retrieval.py`
- EvidencePack builder: `src/agent_ladder/rag/agentic/evidence.py`
- Writer: `src/agent_ladder/rag/agentic/writer.py`
- Verifier: `src/agent_ladder/rag/agentic/verifier.py`
- Trace: `src/agent_ladder/rag/agentic/trace.py`

## Unified source domains

- `paper_corpus`: processed paper metadata, overviews, and chunks.
- `paper_visuals`: figure/table/page metadata via caption/nearby_text/visual_summary.
- `project_docs`: existing Agent Ladder local knowledge outside chapters.
- `chapter_docs`: existing chapter learning docs.

The router does not fork into legacy/new systems. The planner emits domain-specific `SearchUnit`s and the runtime owns all workflow transitions.

## Frontend rendering plan

The assistant answer remains a normal chat message. Extra v0.3 metadata is rendered in the existing Run Margin:

- search units count
- retrieval attempts count
- evidence item count
- verification status
- sources
- visual sources
- image preview through `/api/assets/local` if the file exists and is an image path
- caption-only fallback when no image path exists

## Non-goals

- No Web Search.
- No MCP.
- No long-term Memory.
- No Production Queue.
- No RL.
- No query-time VLM/OCR/ColPali.
- No separate Chapter 3 frontend/API.
