# Chapter 3 Frontend/Backend Real Integration Final Report

## 1. What changed

- Corrected Chapter 3 into the existing FastAPI run endpoint: `POST /api/runs`.
- The endpoint calls `AgenticRAGRuntime` directly and returns typed runtime output: answer, AnswerFrame, language plan, search plan, sources, citations, evidence items, visual sources, verification, retrieval attempts, and run info.
- Safe visual asset serving is available at `GET /api/assets/local?path=<repo-relative-path>`.
- Added a React/Vite page at `/` using the existing Klara/Agent Ladder visual language.
- Added UI panels for final answer, source cards, citations, visual sources, run info, search plan, retrieval attempts, EvidencePack summary, and trace path.
- Added fullstack smoke automation and demo case docs.

## 2. Frontend stack discovered

- `apps/web`
- React 19 + TypeScript + Vite
- Local CSS (`app.css`, `klara.css`), `lucide-react`, `react-markdown`, KaTeX/GFM plugins
- Tests: Vitest + Testing Library + jsdom
- No router dependency; `/` is a page mode inside the existing `App.tsx`.

## 3. Backend/API stack discovered

- `apps/api`
- FastAPI + existing route/dependency/service structure
- Existing v0.2 `/api/runs` remains unchanged and SSE-based
- New Chapter 3 route is synchronous because the runtime is local and bounded

## 4. API contract

`POST /api/runs`

Request:

```json
{
  "question": "给我 10 篇 Agentic RAG 相关论文，并按路线分类",
  "paper_root": "data/papers",
  "run_mode": "standard",
  "include_trace": true
}
```

Response includes:

- `answer`
- `answer_frame`
- `route`
- `run_mode`
- `language_plan`
- `search_plan`
- `sources`
- `citations`
- `evidence_items`
- `visual_sources`
- `rendered_assets`
- `verification`
- `retrieval_attempts`
- `run_info`
- `warnings`

## 5. Visual asset strategy

- Browser never receives Windows absolute paths.
- Only repo-relative asset paths are accepted.
- Existing image assets render through `/api/assets/local?path=...`.
- Text placeholders are returned as `asset_kind=text` and displayed as text cards.
- Missing or caption-only visuals remain visible as caption cards.
- No fake thumbnails, no query-time VLM/OCR/ColPali.

## 6. Demo cases run

See `examples/fullstack/agentic_rag/` and `docs/reports/ch03-fullstack-smoke-report.md`.

| Demo | Query | Result |
| --- | --- | --- |
| 01 | 给我 10 篇 Agentic RAG 相关论文，并按路线分类 | PASS, 10 sources |
| 02 | Explain figure aware RAG in Chinese, include figure | PASS, 1 visual source |
| 03 | 用英文解释 Self-RAG。 | PASS, language control path |
| 04 | Compare ReAct, Reflexion, and Voyager. | PASS, 4 sources |
| 05 | qwerty_nonexistent_agent_ladder_topic | PASS, 0 fabricated sources |
| 06 | 找几篇 world model / spatial world model 相关论文。 | PASS, 10 sources |

## 7. Backend command results

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pytest tests/integration/test_agentic_rag_api.py tests/integration/test_agentic_rag_api_visual_assets.py tests/integration/test_agentic_rag_api_real_runtime.py -q` | PASS, 5 passed |
| `.venv/bin/python -m pytest tests/unit tests/integration -q` | PASS, 43 passed |
| `.venv/bin/python -m agent_ladder.app.cli.main ask-agentic "给我 10 篇 Agentic RAG 相关论文，并按路线分类" --paper-root data/papers` | PASS, 10 sources, verification passed |
| `.venv/bin/python -m agent_ladder.app.cli.main ask-agentic "Explain figure aware RAG in Chinese, include figure" --paper-root data/papers` | PASS, visual source returned, verification passed |

## 8. Frontend command results

| Command | Result |
| --- | --- |
| `cd apps/web && npm run test` | PASS, 18 tests passed |
| `cd apps/web && npm run test:e2e` | PASS, 9 tests passed |
| `cd apps/web && npm run build` | PASS |

## 9. E2E / smoke results

` .venv/bin/python scripts/dev/run_ch03_fullstack_smoke.py `

Result: PASS, 6/6 smoke queries. The script started backend and frontend dev servers, called the real API, checked the `/` frontend route, and wrote `docs/reports/ch03-fullstack-smoke-report.md`.

## 10. Files added/modified

Key added/modified files:

- `apps/api/routes/runs.py`
- `apps/api/services/run_service.py`
- `apps/api/schemas.py`
- `apps/api/dependencies.py`
- `apps/api/main.py`
- `apps/web/src/components/AgenticRagWorkspace.tsx`
- `apps/web/src/components/AgenticRagWorkspace.test.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/domain.ts`
- `apps/web/src/App.tsx`
- `apps/web/src/components/Sidebar.tsx`
- `apps/web/src/styles/app.css`
- `scripts/dev/run_ch03_fullstack_smoke.py`
- `docs/architecture/ch03-frontend-backend-integration-audit.md`
- `docs/reports/ch03-fullstack-smoke-report.md`
- `docs/reports/ch03-visual-rag-ui-report.md`
- `examples/fullstack/agentic_rag/*.md`
- `README.md`
- `docs/chapters/ch03-agentic-rag.md`
- `docs/freezes/v0.3-agentic-rag-freeze.md`

## 11. Known limitations

- Chapter 3 fullstack API is synchronous; streaming progress can be added later without changing the runtime boundary.
- No screenshot automation because the project currently uses Vitest, not Playwright/Cypress.
- Visual RAG remains caption/metadata-based only.
- Real corpus quality depends on processed `data/papers` metadata/chunks/visuals.
- No Web Search, MCP, Memory, Production Queue, real RL, query-time OCR/VLM/ColPali were added.

## 12. Exact commands to run locally

PowerShell:

```powershell
# Backend
.\.venv-win\Scripts\python.exe -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

# Frontend
cd apps\web
npm run dev -- --host 127.0.0.1 --port 5123
```

Open:

```text
http://127.0.0.1:5123
```

Smoke/test:

```powershell
.\.venv-win\Scripts\python.exe scripts\dev\run_ch03_fullstack_smoke.py
.\.venv-win\Scripts\python.exe -m pytest tests\unit tests\integration -q
cd apps\web
npm run test
npm run build
npm run test:e2e
```

## 13. Next recommended fixes

- Add Playwright screenshot capture for visual regression if the project adopts browser E2E.
- Add optional streaming status events for the Chapter 3 page.
- Improve corpus metadata/chunk quality where retrieval is weak; do not weaken verifier strictness.
