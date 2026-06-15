# Klara Reference Synthesis

This note records what Klara should learn from the local ReAct reference tree
and its embedded reference projects without copying their product identities.

Reviewed local sources:

- `C:\Users\brainclos_032\Desktop\ReAct`
- `C:\Users\brainclos_032\Desktop\ReAct\openclaw`
- `C:\Users\brainclos_032\Desktop\ReAct\claw-code`
- `C:\Users\brainclos_032\Desktop\ReAct\hermes-agent`
- `C:\Users\brainclos_032\Desktop\ReAct\learn-claude-code`

## Reference Lessons

### ReAct Runtime

Borrow:

- small generic loop instead of product-specific pipelines
- app-layer harness that assembles persona, tools, context, model, trace, and
  session state
- context engine, capability profiles, memory, skills, background maintenance,
  streaming projection, and trace as separate layers

Do not copy:

- ZENO product identity
- health-specific services
- domain-specific recommendation flows

Klara decision:

ReAct is the closest architectural skeleton. Klara should reuse the principle
of loop-first runtime assembly, but her curriculum should stay more didactic
and chapter-shaped.

### OpenClaw

Borrow:

- `agent-core` versus runtime/app separation
- `AgentContext` style boundary: prompt, messages, tools, and runtime state are
  assembled before the loop
- `AgentLoopConfig` style boundary: model, hooks, context transform, and
  next-turn preparation are configurable inputs
- opt-in hooks with discover/list/check/enable/disable semantics
- skills as discoverable folders with a `SKILL.md` contract
- plugin/resource manifests as a later extension mechanism
- sessions and runtime state as first-class local artifacts

Do not copy early:

- full plugin ecosystem
- marketplace/workshop flows
- large CLI management surface

Klara decision:

Hooks and skills must be first-class in the architecture, but Chapter 1 only
needs the hook runner and one trace hook. Skill discovery belongs after memory
and context are understandable.

### Claw Code

Borrow:

- distinction between a full agent and a minimal controlled agent
- RAG as a separate service/capability rather than the center of the runtime
- safety by default: explicit limits, tool boundaries, and permission classes
- NDJSON/JSONL trace with stable schema and versioning
- parity tests and docs near code

Do not copy early:

- full Rust CLI shape
- shell/MCP-heavy tool surface
- production authentication and credential flows

Klara decision:

The teaching path should keep Chapter 1 intentionally small. File tools,
shell, MCP, and real RAG arrive only after the loop, hooks, capability registry,
and policy boundaries exist.

### Hermes

Borrow:

- self-improvement loop built from traces, skills, memory, and scheduled review
- skills created or improved from repeated experience
- memory nudges and past-session search
- scheduled routines, webhooks, API triggers, and delivery adapters as a
  separate background runtime
- trajectory generation and compression as future eval/training substrate

Do not copy early:

- multi-platform gateway
- background autonomy that silently changes foreground behavior
- broad automation before permissions, audit, and trace are stable

Klara decision:

Background jobs should become "routines" only after foreground loop semantics
are stable. They may propose memory or skill updates, refresh summaries, sample
eval data, or run scheduled research, but they must be traceable and bounded by
restricted capability profiles.

### Claude-Code-Style Learning Surface

Borrow:

- project/user context files as explicit bootstrap material
- compacting as a lifecycle event rather than accidental truncation
- hookable prompt submission and tool use boundaries
- clear separation between instructions, memory, skills, and transcripts

Do not copy:

- vendor-specific behavior or hidden implementation assumptions

Klara decision:

Klara should introduce a `workspace/profile` layer: not as magic, but as
readable bootstrap files and contracts that the harness can load, prioritize,
summarize, and trace.

## Architecture Changes From This Review

1. Add a `workspace` or `profile` layer for project/user bootstrap files.
2. Add a `sessions` layer outside core so transcripts, summaries, compaction,
   and searchable history do not leak into the loop.
3. Split `safety` and `resilience` from generic policy so permission, prompt
   injection, retries, fallback, loop guards, truncation, and recovery can be
   taught explicitly.
4. Treat plugins/extensions as a later chapter that builds on tools, skills,
   and MCP, not as a Chapter 1 concern.
5. Rename background jobs conceptually to routines once scheduling, triggers,
   and delivery adapters appear.
6. Keep RAG behind `knowledge` and `evidence` tools/services.
7. Treat JSONL trace as the seed for eval, policy learning, and future
   trajectory compression.

## Updated Chapter Pressure

Chapter 1 remains Minimal Agent Loop.

It should include:

- loop
- messages
- one fake tool
- prepare-next-turn
- hooks infrastructure
- JSONL trace
- fake LLM tests

It should not include:

- workspace bootstrap files
- real memory
- skill discovery
- real RAG
- plugin runtime
- scheduled routines
- user accounts

The extra reference material strengthens the case for Chapter 1 being smaller,
not larger. The final system can be broad only if the first loop is tiny and
stable.
