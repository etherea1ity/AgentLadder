# Chapter 1 Freeze - Minimal LLM Loop

Date: 2026-06-16

## Frozen Scope

Chapter 1 freezes the smallest runnable Klara loop:

- user, assistant, and tool message contracts
- injected LLM client boundary
- model-visible tool schema and tool observations
- bounded loop policy with `max_turns`
- `prepare_next_turn` as an identity step
- observer hooks for trace and UI projection
- minimal app harness and full-stack API/UI run path
- DeepSeek/Qwen model configuration through repo-local config files
- Python and frontend dependency setup instructions

## Frozen Teaching Claim

An agent run is not one model call. It is a loop:

```text
user input -> LLM -> tool_calls?
  yes -> tools -> observation -> next LLM turn
  no  -> final answer -> stop
```

## Verification

Last verified commands:

```powershell
python -m pytest
npm test -- --run
npm run build
git diff --check
```

Observed results:

- Python tests: 21 passed
- Frontend tests: 8 passed
- Frontend build: passed, with the known Vite chunk-size warning
- Diff check: no whitespace errors

## Deferred To Chapter 2

Chapter 2 starts from this freeze and upgrades the minimal tool path into a real
tool/capability system:

- richer tool registry
- capability profiles and visible-tool selection
- tool namespaces
- tool error contracts
- simple partitioning algorithm for selecting a small allowed tool set
- final-answer turn behavior when loop budget is nearly exhausted
- stronger tool trace events

Chapter 2 still should not introduce RAG, long-term memory, MCP, production auth,
or training/RL.
