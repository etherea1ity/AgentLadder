# Chapter 1 - Minimal Agent Loop

Klara starts as a loop, not a pipeline.

This chapter builds the smallest runtime shape that later chapters can extend:

```text
UserMessage
-> KlaraLoop
-> LLM turn
-> optional ToolCall
-> ToolResult / Observation
-> prepare_next_turn
-> FinalAnswer
-> JSONL Trace
```

## What This Chapter Teaches

- messages: `user`, `assistant`, and `tool`
- model response shape
- tool call and tool result shape
- loop continuation
- stop reasons
- hook emission
- JSONL trace
- harness assembly
- boundary tests

## What It Does Not Teach Yet

- RAG
- memory
- skills
- context compression
- plugins
- routines
- backend/frontend
- eval/RL

Those are later layers. Chapter 1 only creates the heartbeat that those layers
will attach to.

## Reading Order

1. `src/klara/core/messages.py`
2. `src/klara/core/tools.py`
3. `src/klara/core/events.py`
4. `src/klara/core/hooks.py`
5. `src/klara/core/tool_executor.py`
6. `src/klara/core/loop.py`
7. `src/klara/app/harness.py`
8. `tests/klara/core/test_loop.py`
9. `tests/klara/architecture/test_boundaries.py`

## Architectural Boundary

`src/klara/core` is intentionally ignorant. It does not import app, RAG,
memory, skills, backend, eval, training, or production services.

Core is allowed to have several small files. The danger is not file count; the
danger is responsibility creep. In Chapter 1, core is limited to:

- messages
- tool contracts
- events
- hooks
- loop policy
- tool execution boundary
- loop execution

The harness owns assembly:

- persona prompt
- local default user context
- model choice
- visible tools
- trace hook
- loop policy

The loop owns execution:

- ask the model
- execute requested tools
- append observations
- prepare the next turn
- stop with a reason
- emit events
