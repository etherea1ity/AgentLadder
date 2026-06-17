# Chapter 3 Single-Chain Correction Report

## What changed

- Removed the standalone Chapter 3 backend route from the registered FastAPI app.
- Removed the standalone frontend `askAgenticRag` client path and DTOs.
- Kept the original GPT-like chat UI as the only user-facing ask surface.
- Wired `/api/runs` to the unified v0.3 controlled local evidence runtime.
- Extended the v0.3 runtime to search both existing Agent Ladder knowledge (`project_docs`, `chapter_docs`) and the paper corpus (`paper_corpus`, `paper_visuals`) in one `EvidenceSearchPlan`.
- Added generic local asset serving at `/api/assets/local?path=...` for visual cards in the existing Run Margin.
- Updated tests so the default API path is `/api/runs`; `/api/agentic-rag/ask` is expected to be absent.

## Files reverted / moved / kept

- Deleted wrong-chain files: `apps/api/routes/agentic_rag.py`, `apps/api/services/agentic_rag_service.py`.
- Removed wrong-chain frontend client/types from `apps/web/src/api/client.ts` and `apps/web/src/types/domain.ts`.
- Kept and integrated: `src/agent_ladder/rag/agentic/*`, `src/agent_ladder/knowledge/paper/*`, `src/agent_ladder/rag/contracts/agentic.py`.
- Kept existing chat UI and extended `apps/web/src/components/RunMargin.tsx`.

## Single backend chain

```text
ChatWorkspace
→ api.createRun('/api/runs')
→ apps/api/routes/runs.py
→ apps/api/services/run_service.py
→ AgenticRAGRuntime
→ RequestSpec / EvidenceSearchPlan / EvidencePack / AnswerFrameV2 / VerificationResult
→ Jsonl trace + SSE events
→ ChatWorkspace + RunMargin
```

## Contracts used

`RequestSpec`, `LanguagePlan`, `AnswerRequirement`, `RouteState`, `SearchUnit`, `EvidenceSearchPlan`, `SearchRequest`, `SearchHit`, `FetchRequest`, `FetchResult`, `EvidenceItem`, `EvidencePack`, `AnswerFrameV2`, `VerificationResult`, `DecisionRecord`, `BudgetState`, `FailurePolicy`, `WorkflowState`, `SourceCard`, `Citation`.

## Validation results

| Command | Result |
| --- | --- |
| `AGENT_LADDER_PAPER_ROOT=data/papers .venv/bin/python -m pytest tests/unit tests/integration -q` | PASS: 44 passed in 497.28s |
| `AGENT_LADDER_PAPER_ROOT=data/papers .venv/bin/python -m pytest tests/test_api_sse.py -q` | PASS: 3 passed in 100.12s |
| `cd apps/web && npm run test` | PASS: 16 passed |
| `cd apps/web && npm run build` | PASS |
| `AGENT_LADDER_PAPER_ROOT=data/papers .venv/bin/python scripts/dev/run_ch03_fullstack_smoke.py` | PASS: 7/7 smoke queries |
| `AGENT_LADDER_PAPER_ROOT=data/papers .venv/bin/python -m agent_ladder.app.cli.main ask-agentic "Explain figure aware RAG in Chinese, include figure"` | PASS |

## Smoke highlights

- `tell me about react` returns ReAct paper evidence through `/api/runs`.
- Requested count 10 returns 10 sources with planner budgets larger than final count.
- Visual query returns a visual source card; caption-only visuals remain visible without fake image paths.
- Nonexistent query returns `insufficient_info`, not a mock answer.
- Klara persona is present in final answer text.

## Known limitations

- Runtime is deterministic/local; no streaming token-by-token from an LLM worker yet.
- Some visual entries have caption metadata but no extracted image path; UI shows caption cards for those.
- Full local corpus smoke is slow because it scans the processed corpus directly.
