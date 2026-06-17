# Chapter 3 Frontend / Backend Integration Audit

## Goal

Connect the real Chapter 3 Agentic RAG runtime to the existing Agent Ladder frontend/backend stack. This is not a mock UI task; the API must call `AgenticRAGRuntime` and the frontend must render the real response.

## Actual frontend stack

- Directory: `apps/web`
- Framework: React 19 + TypeScript + Vite
- Styling: local CSS files, mainly `apps/web/src/styles/app.css` and `apps/web/src/styles/klara.css`
- Markdown rendering: `react-markdown` with GFM/math/KaTeX plugins
- Icons: `lucide-react`
- Tests: Vitest + Testing Library + jsdom
- Package manager: npm, with scripts in `apps/web/package.json`

Actual commands:

```bash
cd apps/web
npm install
npm run test -- --run
npm run build
npm run test:e2e
npm run dev
```

## Actual frontend entrypoints and design patterns

- Main entry: `apps/web/src/main.tsx`
- Root component: `apps/web/src/App.tsx`
- API client: `apps/web/src/api/client.ts`
- Domain types: `apps/web/src/types/domain.ts`
- Main chat: `apps/web/src/components/ChatWorkspace.tsx`
- Run margin: `apps/web/src/components/RunMargin.tsx`
- Klara run cards/presence: `apps/web/src/components/klara/KlaraRunPanel.tsx`, `KlaraRunStatus.tsx`, `KlaraPresence.tsx`

Current UI language:

- Warm paper/ink visual system.
- Sidebar + centered chat + optional right Run Margin.
- Klara presence/status controls for run lifecycle.
- Structured run details are shown as cards/details in the Run Margin.
- Existing route is currently single-page chat; no router library is present.

## Actual backend/API stack

- Directory: `apps/api`
- Framework: FastAPI
- Entry: `apps/api/main.py`
- Existing routers:
  - `apps/api/routes/sessions.py`
  - `apps/api/routes/runs.py`
  - `apps/api/routes/models.py`
- Dependency wiring: `apps/api/dependencies.py`
- Storage: JSONL app store under `data/app`
- Streaming: SSE bus under `apps/api/services/sse_bus.py`
- Existing run path: `POST /api/runs` creates a Klara v0.2 run, streams LLM answer deltas, and stores run events.

Actual backend command:

```bash
uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

## Actual Chapter 3 runtime entrypoints

- CLI: `src/agent_ladder/app/cli/main.py`, subcommand `ask-agentic`
- Runtime: `src/agent_ladder/rag/agentic/runtime.py`, class `AgenticRAGRuntime`
- Contracts: `src/agent_ladder/rag/contracts/agentic.py`
- Providers: `src/agent_ladder/rag/agentic/providers.py`
- Corpus root support: `AgenticRAGRuntime(paper_root="data/papers")`

CLI already works with real corpus:

```bash
python -m agent_ladder.app.cli.main ask-agentic "给我 10 篇 Agentic RAG 相关论文，并按路线分类" --paper-root data/papers
```

## Actual paper/visual asset state

- Real corpus root: `data/papers`
- Processed papers: `data/papers/processed/<paper_id>`
- Visual metadata: `visuals.jsonl`
- Image assets may be `.png/.jpg/.jpeg/.webp/.svg`
- Some visual assets may be text placeholders such as `.txt`; these must be rendered as caption/text cards, not fake images.

Browser cannot load arbitrary local file paths directly. The backend must expose a safe route that maps repo-relative `data/papers/...` paths to static responses.

## Files to modify

Backend/API:

```text
apps/api/main.py
apps/api/schemas.py
apps/api/routes/runs.py
apps/api/services/run_service.py
apps/api/dependencies.py
```

Frontend:

```text
apps/web/src/api/client.ts
apps/web/src/types/domain.ts
apps/web/src/App.tsx
apps/web/src/components/AgenticRagWorkspace.tsx
apps/web/src/styles/app.css
```

Tests:

```text
tests/integration/test_agentic_rag_api.py
tests/integration/test_agentic_rag_api_visual_assets.py
tests/integration/test_agentic_rag_api_real_runtime.py
apps/web/src/components/AgenticRagWorkspace.test.tsx
```

Scripts/reports/examples:

```text
scripts/dev/run_ch03_fullstack_smoke.py
docs/reports/ch03-fullstack-smoke-report.md
docs/reports/ch03-visual-rag-ui-report.md
examples/fullstack/agentic_rag/*.md
```

## Actual API contract

```http
POST /api/runs
```

Request:

```json
{
  "question": "给我 10 篇 Agentic RAG 相关论文，并按路线分类",
  "paper_root": "data/papers",
  "run_mode": "standard",
  "include_trace": true
}
```

Response is built from real `AgenticRAGRuntime` output and includes:

- answer
- answer_frame
- route
- run_mode
- language_plan
- search_plan
- sources
- citations
- evidence_items
- visual_sources
- rendered_assets
- verification
- run_info
- warnings

## Risks and missing pieces

1. Current frontend does not use a router; Chapter 3 should be a page mode inside existing App, not a new routing framework.
2. Current `/api/runs` path is streaming/SSE for Chapter 2 Klara. Chapter 3 can start as synchronous API because the runtime is bounded and local.
3. Visual asset serving must not leak Windows absolute paths.
4. Large real corpus makes API responses heavy if raw evidence text is sent unbounded; the API should return typed runtime fields but keep frontend display summaries manageable.
5. Existing design says Run Margin is for trace/activity; Chapter 3 page should reuse the right-panel concept rather than replace the whole site.
6. No Web Search, MCP, Memory, Production Queue, RL, query-time OCR/VLM/ColPali should be added.

## Implemented integration notes

- Backend router: `apps/api/routes/runs.py`
- Backend service: `apps/api/services/run_service.py`
- Frontend page: `apps/web/src/components/AgenticRagWorkspace.tsx`
- Frontend route mode: Chapter 3 is the root homepage (`/`) in `App.tsx`; no extra router dependency is introduced.
- Safe asset route: `GET /api/assets/local?path=<repo-relative-path>`
- Fullstack smoke report: `docs/reports/ch03-fullstack-smoke-report.md`

No mock answer path is used by the API; component tests mock HTTP only at the browser test boundary.


## Single-chain correction

The standalone Chapter 3 API/page identified in the original audit was a wrong-chain addition. The corrected architecture uses the existing chat run endpoint `POST /api/runs`; visual assets use `GET /api/assets/local?path=<repo-relative-path>`. `apps/api/routes/runs.py` and `apps/api/services/run_service.py` were removed.
