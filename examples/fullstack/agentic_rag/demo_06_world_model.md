# Demo 06 — World Model

- user query: `找几篇 world model / spatial world model 相关论文。`
- expected route: `rag`
- expected source domain: `paper_corpus`
- expected visual behavior: no visual required; visual panel remains available.
- backend command: `.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`
- API call: `POST /api/runs` with `paper_root=data/papers`
- frontend route: `http://127.0.0.1:5123`
- screenshots path: not generated; see smoke report.
- pass/fail result: PASS in `docs/reports/ch03-fullstack-smoke-report.md` — 10 sources, 10 evidence items, 6 retrieval attempts, verification `passed`.
