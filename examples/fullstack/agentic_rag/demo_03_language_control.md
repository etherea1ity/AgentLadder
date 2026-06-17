# Demo 03 — Language Control

- user query: `用英文解释 Self-RAG。`
- expected route: `rag`
- expected source domain: `paper_corpus`
- expected visual behavior: no visual required.
- backend command: `.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`
- API call: `POST /api/runs` with `paper_root=data/papers`
- frontend route: `http://127.0.0.1:5123`
- screenshots path: not generated; see smoke report.
- pass/fail result: PASS in `docs/reports/ch03-fullstack-smoke-report.md` — 2 sources, verification `passed`; internal paper retrieval uses English canonical query while final output follows explicit English request.
