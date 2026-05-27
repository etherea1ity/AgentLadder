---
name: agent-ladder-webapp
description: Build or plan the Agent Ladder v0.1 Minimal Agent full-stack webapp. Use when asked to implement the Agent Ladder UI shown in the reference image, frontend/backend split, Run Margin, ThinkingInlineBar, sessions/messages/runs/events, JSONL persistence, SSE streaming, deletion/rename/cancel behavior, tests, audit, and freeze docs for v0.1.
---

# Agent Ladder Webapp

## Operating rule

Execute autonomously to completion when invoked through `/goal` or an equivalent goal workflow. Do not ask for permission on ordinary local planning, file creation, implementation, testing, or verification. If a phase fails review or tests, revise the plan or code and rerun the required checks. Ask only for missing credentials, destructive external actions, or scope changes outside v0.1.

## Load first

Read `references/v0.1-webapp-spec.md` before planning or editing. It is the authoritative product, architecture, API, storage, test, audit, and visual contract for this skill.

## Mission

Deliver Agent Ladder v0.1 as a quiet learning workspace that shows how one question becomes an observable run:

`User question → Session/Message/Run → AskState → MinimalAgent → LLM → AnswerState → RunLog → JSONL Trace → UI answer + Run Margin`

The implementation must preserve the existing `src/agent_ladder/` core package and add frontend/backend around it rather than moving core code into the app layer.

## Required repository layout

Use this layout unless the existing repo already contains an equivalent path:

```text
src/agent_ladder/          # reusable agent core library, not UI app code
apps/api/                  # FastAPI backend application
apps/web/                  # React + TypeScript + Vite frontend application
data/app/                  # sessions/messages/runs/run_events JSONL stores
data/traces/               # agent trace JSONL store
docs/product/              # UX and visual specs
docs/architecture/         # frontend/backend/core/integration specs
docs/reviews/              # discovery and audit reports
docs/chapters/             # chapter tutorial
docs/freezes/              # freeze report
```

Do not place the React frontend under `src/agent_ladder/`. Do not make the frontend call an LLM directly.

## Non-negotiable v0.1 scope

Implement only:

- New Chat with lazy session creation.
- Normal question/answer chat.
- Backend-created sessions, messages, runs, and run events.
- Streaming answer display using SSE.
- Safe ThinkingInlineBar activity states.
- Click ThinkingInlineBar or Details to open selected-run Run Margin.
- JSONL app persistence and JSONL trace persistence.
- Rename/delete sessions, with backend-backed soft delete.
- Cancel endpoint and UI stop behavior; if true LLM cancellation is limited, document the limitation and prevent cancelled output from updating the visible assistant message.
- Tests and real end-to-end validation.

Do not implement RAG, memory, research, MCP, eval dashboard, RL, auth, billing, file upload, complex settings, graph visualization, or raw chain-of-thought display.

## Visual target

Match the provided UI reference: warm paper background, calm ink typography, minimal left sidebar, centered chat, and right Run Margin that appears only for a selected run. The UI must be English-only. Avoid neon, cyber, heavy gradients, dashboard density, dark enterprise sidebars, excessive cards, and excessive icons.

## Required multi-role planning outputs

Before implementation, produce these files and cross-check them against `references/v0.1-webapp-spec.md`:

1. `docs/reviews/v0.1-current-state.md`
2. `docs/product/v0.1-interaction-spec.md`
3. `docs/product/v0.1-visual-system.md`
4. `docs/architecture/v0.1-frontend-architecture.md`
5. `docs/architecture/v0.1-backend-api-storage.md`
6. `docs/architecture/v0.1-agent-core-run-lifecycle.md`
7. `docs/architecture/v0.1-integration-plan.md`
8. `docs/reviews/v0.1-ui-ux-api-audit.md`

Use native subagents for independent roles when available: designer/UX, frontend architect, backend architect, core lifecycle, integration, QA/audit, documentation. If subagents are unavailable, perform the role passes sequentially and label each report clearly. Do not skip review because implementation feels obvious.

## Implementation order

Follow this order and rerun checks after each major block:

1. Discovery report; no code changes beyond skill/doc artifacts.
2. Product interaction spec and visual system.
3. Architecture contracts: TypeScript types, API schemas, SSE events, Python models, storage formats.
4. Core lifecycle adjustments needed for streaming/events while keeping `src/agent_ladder/` UI-agnostic.
5. Backend API, JSONL storage, run lifecycle service, SSE stream, cancel/delete/rename.
6. Frontend AppShell, Sidebar, ChatWorkspace, ThinkingInlineBar, RunMargin, responsive layout.
7. Unit, API, SSE, frontend component, UI/e2e tests.
8. Documentation, audit, freeze report.
9. Final real validation and concise completion report.

## Core contracts

Keep the core independent from FastAPI and React. It may expose:

- `AskState`
- `AnswerState`
- `RunLog`
- `RunEvent`
- streaming/event-emitting run lifecycle helpers
- JSONL trace payloads

The API layer owns sessions/messages/runs/events storage and SSE delivery. The frontend owns display state only.

## Frontend invariants

- Run Margin is not rendered when `selectedRunId` is null.
- Sending a message must not open Run Margin automatically.
- ThinkingInlineBar is a real button with `aria-expanded`, `aria-controls`, and an accessible label.
- `assistantMessage.run_id` is the binding between an answer and a run.
- Run Margin reads only the selected run.
- Switching sessions closes Run Margin and clears `selectedRunId`.
- `answer_delta` updates assistant content but does not create one timeline row per delta.
- No raw chain-of-thought is displayed or stored for UI use.

## Backend invariants

- All user-visible delete/rename operations call backend APIs.
- Deleted sessions are hidden from normal session/message/run GET endpoints.
- JSONL storage is append-only for teaching/audit; session delete uses a tombstone event.
- SSE streams historical events first, then live events, so the frontend does not miss events between `POST /api/runs` and `EventSource` connection.
- SSE disconnect reconciliation uses `GET /api/runs/{run_id}` if the frontend did not observe a terminal event.

## Verification gate

Do not claim completion until all applicable checks pass or a documented external blocker remains:

- Python unit tests for contracts/storage/run lifecycle.
- API tests for sessions, runs, delete, rename, cancel.
- SSE integration test for event order and answer deltas.
- Frontend typecheck/build.
- Frontend component tests for ThinkingInlineBar states and RunMargin selection behavior.
- UI/e2e test: create session → ask → stream answer → click thinking → Run Margin → completed log/trace → delete → refresh and verify deletion.
- Visual audit against warm paper/ink/margin reference and explicit non-goals.

## Final response contract

End with:

- What was implemented.
- How to run backend and frontend.
- How to test.
- E2E validation result.
- Known limitations.
- What is postponed to v0.2.
- Textual UI walkthrough and screenshot path if screenshots were captured.
