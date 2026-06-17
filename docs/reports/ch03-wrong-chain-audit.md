# Chapter 3 Wrong-Chain Audit

Status: corrected toward one main chat chain.

## Principle

Agent Ladder v0.3 is one unified Klara ask chain. The existing GPT-like chat UI remains the only product surface. Chapter 3 functionality is not a standalone demo app/API; it is the controlled local evidence runtime behind the existing `/api/runs` chat submission path.

## Wrong additions found

| Area | File / surface | Status | Decision |
| --- | --- | --- | --- |
| Standalone backend route | `apps/api/routes/agentic_rag.py` (`/api/agentic-rag/ask`, `/api/agentic-rag/assets`) | wrong chain | Delete candidate; not registered in `apps/api/main.py`. Asset serving moved to `/api/assets/local` for the main chat UI. |
| Standalone backend service | `apps/api/services/agentic_rag_service.py` | wrong chain | Delete candidate; runtime invocation belongs behind `RunService` / main ask path. Useful asset ideas moved to the main asset route. |
| FastAPI router include | `apps/api/main.py` importing `agentic_rag_router` | wrong chain | Removed. Only sessions/models/runs/assets are registered. |
| API dependency | `apps/api/dependencies.py:get_agentic_rag_service` | wrong chain | Removed. Main `RunService` owns the ask execution path. |
| Standalone frontend client | `apps/web/src/api/client.ts:askAgenticRag` | wrong chain | Removed. Frontend submits through `api.createRun('/api/runs')`. |
| Standalone frontend DTOs | `apps/web/src/types/domain.ts:AgenticRag*` | wrong chain | Removed. The chat UI reads v0.3 data from the run trace / module results instead of calling a separate API. |
| Standalone Chapter 3 page/component | `apps/web/src/components/AgenticRagWorkspace.tsx` and test | wrong chain | Already removed before this audit. |
| Standalone Chapter 3 page CSS | `.agentic-page` / separate demo layout | wrong chain | Already removed before this audit. |

## Kept and moved into the main chain

| Area | File / surface | Status | Why it stays |
| --- | --- | --- | --- |
| Controlled runtime | `src/agent_ladder/rag/agentic/runtime.py` | keep | This is now the single v0.3 AskRuntime-style path behind the existing chat run. |
| Contracts | `src/agent_ladder/rag/contracts/agentic.py` | keep | Typed contracts define RequestSpec, EvidencePack, AnswerFrameV2, VerificationResult, DecisionRecord, WorkflowState. |
| Paper corpus | `src/agent_ladder/knowledge/paper/*`, `data/papers/*` | keep | Knowledge layer for local papers; not an API/runtime fork. |
| Existing local docs | `data/knowledge/*` | keep | Integrated as `project_docs` / `chapter_docs` source domains inside the same v0.3 retrieval plan. |
| Existing chat UI extension | `apps/web/src/components/RunMargin.tsx` | keep | Displays optional route/search/evidence/visual panels inside the original Run Margin. |
| Main visual asset serving | `apps/api/routes/assets.py` | keep | Generic local asset route for the existing chat UI; not a RAG demo endpoint. |
| Smoke script | `scripts/dev/run_ch03_fullstack_smoke.py` | keep | Must target `/api/runs`, not `/api/agentic-rag/ask`. |

## Needs user confirmation before any destructive cleanup

- Large local corpus artifacts under `data/papers/raw`, `data/papers/processed`, and extracted page images: do not delete automatically.
- Whether to commit real processed corpus or keep only fixtures + reports in Git.

## Current correction

- Existing Chat UI → `api.createRun` → `/api/runs` → `RunService` → unified v0.3 controlled local evidence runtime.
- The runtime searches both existing Agent Ladder knowledge (`project_docs`, `chapter_docs`) and paper corpus (`paper_corpus`, `paper_visuals`) as source domains in one `EvidenceSearchPlan`.
- No default frontend path calls `/api/agentic-rag/ask`.
