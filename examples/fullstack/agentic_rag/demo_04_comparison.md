# Demo 04 — Comparison

- user query: `Compare ReAct, Reflexion, and Voyager.`
- expected route: `rag`
- expected source domain: `paper_corpus`
- expected visual behavior: no visual required.
- backend command: `.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`
- API call: `POST /api/runs` with `paper_root=data/papers`
- frontend route: `http://127.0.0.1:5123`
- screenshots path: not generated; see smoke report.
- pass/fail result: PASS in `docs/reports/ch03-fullstack-smoke-report.md` — 4 sources, 4 evidence items, 6 retrieval attempts, verification `passed`.
