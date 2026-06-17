# Demo 01 — Requested Count 10

- user query: `给我 10 篇 Agentic RAG 相关论文，并按路线分类`
- expected route: `rag`
- expected source domain: `paper_corpus`
- expected visual behavior: no visual required; UI should show source cards and run metadata.
- backend command: `.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`
- API call: `POST /api/runs` with `paper_root=data/papers`
- frontend route: `http://127.0.0.1:5123`
- screenshots path: not generated; see smoke report.
- pass/fail result: PASS in `docs/reports/ch03-fullstack-smoke-report.md` — 10 sources, 14 evidence items, 6 retrieval attempts, verification `passed`.
