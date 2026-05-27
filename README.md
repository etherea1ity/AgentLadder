# Agent Ladder

From Prompt to Policy.

Agent Ladder is a staged learning repository for moving from a single LLM API call toward more capable agent systems: RAG, Agentic RAG, Memory, Research, MCP, Production, Eval, and RL for agents.

## Current branch

`v0.1-minimal-agent` — Minimal Agent: From API Call to Ask / Answer.

This version builds a quiet full-stack learning workspace:

- Ask a normal question.
- Stream the answer from the real DashScope/OpenAI-compatible provider.
- See a safe ThinkingInlineBar.
- Click it to open the Run Margin.
- Inspect the run timeline, run log, and JSONL trace.

## One-command start

From Windows PowerShell, run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Open `http://127.0.0.1:5173`.

Stop both ports:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Stop
```

## Real LLM configuration

Create a local `.env` with:

```env
DASHSCOPE_API_KEY=your_dashscope_api_key_here
```

The runtime path is real DashScope/Qwen via the OpenAI-compatible API.

## Manual run

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

## Test

```bash
.venv/bin/pytest -q
npm --prefix apps/web run build
npm --prefix apps/web run test -- --run
npm --prefix apps/web run test:e2e -- --run
```

## v0.1 scope

Included:

- AskState / AnswerState / RunLog
- DashScope LLM provider
- FastAPI backend
- React + TypeScript frontend
- sessions/messages/runs/events
- SSE streaming
- JSONL app storage and traces
- Run Margin

Not included:

- RAG
- Memory
- Research
- MCP
- Eval / RL
- auth
- file upload
- raw chain-of-thought display
