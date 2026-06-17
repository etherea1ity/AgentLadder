# Demo 05 — Insufficient Info

- user query: `This query should not match anything: qwerty_nonexistent_agent_ladder_topic`
- expected route: `rag`
- expected source domain: none or empty paper evidence.
- expected visual behavior: no visual source; UI should show empty visual panel rather than hide the section.
- backend command: `.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`
- API call: `POST /api/runs` with `paper_root=data/papers`
- frontend route: `http://127.0.0.1:5123`
- screenshots path: not generated; see smoke report.
- pass/fail result: PASS in `docs/reports/ch03-fullstack-smoke-report.md` — 0 sources, 0 evidence items, 10 retrieval attempts, verification `passed`; runtime returns insufficient/partial behavior instead of fabricating sources.
