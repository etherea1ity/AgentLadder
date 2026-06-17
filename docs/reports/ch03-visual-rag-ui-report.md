# Chapter 3 Visual RAG UI Report

## Scope

The Chapter 3 UI renders real visual evidence returned by the Agentic RAG runtime. It does not run query-time VLM, OCR, ColPali, web search, MCP, memory, production queue, eval runner, or RL.

## Backend visual asset strategy

- Visual metadata comes from `AnswerFrameV2.visual_sources` and `rendered_assets`.
- The API decorates each visual source with:
  - `asset_kind`: `image`, `text`, `missing`, `none`, `blocked`, or `file`
  - `asset_url`: safe `/api/assets/local?path=<repo-relative-path>` only when the path exists
  - `text_preview`: for text assets
- Only repo-relative paths are served. Windows absolute paths and path traversal are blocked.
- Image extensions are `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, `.gif`.
- Text placeholders such as `.txt`, `.md`, `.json`, `.jsonl`, `.csv` are not treated as images.

## Frontend visual behavior

- `asset_kind=image` + `asset_url`: render an image preview.
- `asset_kind=text`: render a text preview card.
- `asset_kind=none/missing/blocked/file`: render a caption card and keep source metadata visible.
- Caption-only visual evidence is not hidden and no fake thumbnail is created.

## Verified demo evidence

Fullstack smoke query:

```text
Explain figure aware RAG in Chinese, include figure
```

Result from `docs/reports/ch03-fullstack-smoke-report.md`:

- route: `rag`
- run_mode: `agentic_rag`
- sources: 10
- visual sources: 1
- evidence items: 10
- retrieval attempts: 7
- verification: `passed`

## Tests

- `tests/integration/test_agentic_rag_api_visual_assets.py` verifies safe visual asset decoration and text placeholders.
- `apps/web/src/components/AgenticRagWorkspace.test.tsx` verifies image visual card and caption-only visual card rendering.

## Known limitations

- No screenshot automation is included yet; this project currently uses Vitest, not Playwright/Cypress.
- Visual retrieval is caption/metadata based only.
- Missing image files are displayed as missing/caption cards instead of being fabricated.
