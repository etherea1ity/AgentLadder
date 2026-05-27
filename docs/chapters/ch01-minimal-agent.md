# Chapter 1: Minimal Agent

## Goal

Build the smallest useful Agent Ladder system: a user asks a question, the backend creates a run, the agent calls an LLM, the answer streams into the UI, and the run is saved as a trace.

## What v0.1 teaches

- `AskState` represents the user's input.
- `AnswerState` represents the agent output.
- `RunLog` records observability details.
- `RunEvent` records UI-safe lifecycle events.
- JSONL traces make future eval and RL possible.
- The Run Margin shows how one answer became a run without exposing raw chain-of-thought.

## Flow

```text
User question
→ Session / Message / Run
→ AskState
→ DashScope LLM client
→ streamed answer deltas
→ AnswerState
→ RunLog
→ JSONL trace
→ ThinkingInlineBar + Run Margin
```

## How to run

Backend:

```bash
python3 -m pip install -e ".[dev]"
uvicorn apps.api.main:app --reload --port 8000
```

Frontend:

```bash
cd apps/web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Known limitations

- v0.1 uses local JSONL storage, not a database.
- Cancellation is best-effort for active LLM streams.
- No RAG, memory, research, MCP, eval, or RL features are implemented.
- No user accounts or multi-user isolation.
