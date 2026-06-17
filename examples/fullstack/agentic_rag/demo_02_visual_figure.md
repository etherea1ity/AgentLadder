# Demo 02 — Visual Figure

- user query: `Explain figure aware RAG in Chinese, include figure`
- expected route: `rag`
- expected source domain: `paper_corpus` plus visual metadata from `paper_visuals`/visual source records where available.
- expected visual behavior: visual source card must show image preview when `asset_kind=image`; otherwise caption card. It must not fake thumbnails.
- backend command: `.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`
- API call: `POST /api/runs` with `paper_root=data/papers`
- frontend route: `http://127.0.0.1:5123`
- screenshots path: not generated; see smoke report.
- pass/fail result: PASS in `docs/reports/ch03-fullstack-smoke-report.md` — 10 sources, 1 visual source, 10 evidence items, verification `passed`.
