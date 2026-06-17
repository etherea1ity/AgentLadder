# Chapter 3: Agentic RAG — Klara's Controlled Research Runtime

> From fixed retrieval to controlled evidence search.

Chapter 3 upgrades Klara from Chapter 2's fixed RAG chain into a bounded local research runtime. It still uses local data only, but it now treats retrieval as a planned, observable workflow: normalize the request, plan multiple search paths, fuse/dedup/rerank results, fetch evidence, build an EvidencePack, write from the pack only, verify citations/claims/language, and save DecisionRecords.

## Core principle

Klara does **not** run a free autonomous agent loop in this chapter. The runtime owns workflow transitions, budgets, retry policy, trace, and schema validation. LLM-like workers are represented as controlled one-shot workers that accept and return typed Pydantic contracts.

## New concepts

- `RequestSpec`: normalized user request, canonical English query, output language, and answer requirements.
- `EvidenceSearchPlan`: multi-path local paper search plan with candidate budgets.
- `SearchProvider` / `FetchProvider`: local-paper search/fetch abstraction that will later fit web research.
- `EvidencePack`: writer-safe evidence boundary; the writer does not read raw chunks.
- `AnswerFrameV2`: answer mode, claims, sources, evidence items, citations, visual sources, rendered assets, and final text.
- `DecisionRecord`: every route, budget, retrieval, rewrite, evidence, and verification choice becomes trace data.

## How to run

```bash
python -m agent_ladder.app.cli.main ask-agentic "给我 10 篇 Agentic RAG 相关论文，并按路线分类"
python -m agent_ladder.app.cli.main ask-agentic "Explain figure aware RAG in Chinese, include figure"
python -m agent_ladder.app.cli.main ask-agentic "给我 10 篇 Agentic RAG 相关论文，并按路线分类" --paper-root data/papers
```

The command prints Question, Answer, Sources, Visual Sources, and run info including route, run mode, search unit count, retrieval attempts, evidence item count, verification status, latency, and trace status.

## Fullstack demo

The existing React/Vite frontend now has a Chapter 3 page at:

```text
http://127.0.0.1:5123
```

Backend:

```bash
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd apps/web
npm run dev -- --host 127.0.0.1 --port 5123
```

The page calls the real FastAPI endpoint `POST /api/runs`, which invokes `AgenticRAGRuntime`. It renders the final answer, route, run mode, search units, retrieval attempts, EvidencePack count, verification status, sources, citations, visual sources, visual asset kind, and trace path.

Visual assets are served through the safe backend route `GET /api/assets/local?path=<repo-relative-path>`. Existing image files render as previews; caption-only or text-placeholder visuals render as metadata cards and are not hidden.

## Fixture paper corpus

Chapter 3 uses `data/papers/fixtures/` so the runtime works without downloading papers:

- `paper_agentic_rag`: Agentic RAG / Self-RAG-style fixture with a table.
- `paper_world_model`: world model fixture for route diversity.
- `paper_visual_transformer`: multimodal/figure-aware fixture with a figure.

The standard future corpus shape is documented in `docs/architecture/ch03-agentic-rag-architecture.md`.

## Real corpus and reports

When local processed papers exist under `data/papers/processed`, use `--paper-root data/papers` or set `AGENT_LADDER_PAPER_ROOT=data/papers`.

Useful reports:

- `docs/architecture/ch03-frontend-backend-integration-audit.md`
- `docs/reports/ch03-fullstack-smoke-report.md`
- `docs/reports/ch03-visual-rag-ui-report.md`

## What is postponed

Web search, MCP tools, long-term memory, production queues, eval dashboards, real RL, OCR, query-time VLM, ColPali/page-as-image retrieval, and PDF download/cleaning are intentionally outside this chapter.
