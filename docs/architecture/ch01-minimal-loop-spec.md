# Chapter 1 Spec - Minimal Agent Loop

## Goal

Build Klara's smallest real runtime shape: a loop, not a pipeline.

Chapter 1 should prove that Klara can:

1. receive a user message
2. call an LLM client
3. optionally execute one tool call
4. feed the tool result back as an observation
5. prepare the next turn
6. stop with a final answer
7. emit trace events throughout

## Teaching Narrative

The old minimal-agent story was:

```text
Question -> AskState -> LLM -> AnswerState -> RunLog -> Trace
```

The new Klara story is:

```text
UserMessage
-> KlaraLoop
-> LLM turn
-> optional ToolCall
-> ToolResult / Observation
-> prepare_next_turn
-> FinalAnswer
-> Event Trace
```

The no-tool case is still taught first. It is simply the smallest case of the same loop.

## Required Concepts

### Message

Minimum roles:

- `user`
- `assistant`
- `tool`

### LLM Client

Protocol only:

- receives system prompt, messages, tools, model
- returns assistant content and optional tool calls

Chapter 1 should use a fake LLM in tests and optionally a real provider in examples.

### Tool

Minimum shape:

- name
- description
- input schema
- execute
- result

One fake or deterministic tool is enough.

### Loop

Minimum loop:

```text
start run
start turn
call model
append assistant message
if no tool calls: stop
execute tool calls
append tool results
prepare next turn
continue until final or max turns
end run
```

### Hooks

Chapter 1 should include hook infrastructure even if only trace uses it.

Minimum events:

- `run.started`
- `turn.started`
- `llm.started`
- `llm.completed`
- `tool.started`
- `tool.completed`
- `prepare_next_turn.started`
- `prepare_next_turn.completed`
- `turn.completed`
- `run.completed`
- `run.failed`

### Trace

Trace is JSONL event output.

Trace should not include:

- raw secrets
- private hidden reasoning
- full private prompt bodies by default

Trace may include:

- run id
- event type
- timestamp
- model id
- tool names
- public summaries
- latency
- token usage if available
- stop reason

## Non-goals

Chapter 1 should not implement:

- RAG
- memory
- skills
- workspace/profile bootstrap files
- context compression
- plugins/extensions
- scheduled routines
- production backend
- frontend UI polish
- MCP
- eval scoring
- RL

Those are later chapters.

## Acceptance Criteria

- No-tool run returns a final answer.
- One-tool run executes the tool, feeds back the result, then returns a final answer.
- Loop stops at max turns if the model keeps requesting tools.
- Hook failures do not crash the run.
- JSONL trace contains run, LLM, tool, prepare, and completion events.
- Core imports no RAG, memory, skills, backend, eval, training, or service modules.
- Tests use a fake LLM and fake tool.

## First Files To Create During Implementation

```text
src/klara/core/messages.py
src/klara/core/tools.py
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/policies.py
src/klara/core/tool_executor.py
src/klara/core/loop.py
src/klara/app/harness.py
src/klara/capabilities/registry.py
src/klara/capabilities/tools/fake_tool.py
docs/chapters/ch01-minimal-agent-loop.md
tests/klara/core/test_loop.py
tests/klara/core/test_hooks.py
tests/klara/architecture/test_boundaries.py
```

This list is for the future implementation branch. This documentation branch should not add those code files.
