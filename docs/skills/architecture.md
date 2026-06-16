# Klara Architecture Reference

## Identity

```text
AgentLadder/        curriculum repository
Klara               product/persona/runtime built inside the curriculum
src/klara/          runtime package
docs/chapters/      teaching sequence
docs/skills/        compact project rules and route decisions
```

Klara should feel like Klara: calm, branch-aware, observable, and honest about what she can and cannot do.

## Runtime Boundary

`src/klara/core` owns only the minimal runtime mechanics:

- messages
- model turns
- tool call/result contracts
- tool executor boundary
- lifecycle events
- hook fanout
- loop policy
- stop reasons
- loop execution

`src/klara/core` must not import:

- app
- concrete capabilities
- context
- memory
- skills
- services
- backend
- eval
- training

If a later capability needs to affect a run, attach it through app assembly, hooks, capabilities, context, trace, or service adapters. Do not turn core into a product pipeline.

## Layer Responsibilities

- `app`: assemble persona, user context, model choice, visible tools, hooks, trace sinks, and loop policy.
- `capabilities`: register and expose tools by chapter/profile.
- `context`: budget, priority, compaction, summaries, next-turn preparation.
- `memory`: durable continuity with explicit remember/update/delete/search policies.
- `skills`: procedural memory for repeatable work.
- `services`: knowledge, RAG, web, storage, MCP, evidence, external adapters.
- `backend`: HTTP/SSE/session APIs and frontend-safe projections.
- `infra`: config, LLM providers, observability, storage adapters.
- `eval` and `training`: consume traces to improve policy and routing later.

## Hook Principle

Hook is a lifecycle extension point, not an LLM-visible tool.

Use these categories:

- Observer hook: trace, metrics, frontend event projection.
- Decision hook: pre-tool guard, block/allow/rewrite decisions.
- Stop hook: completion cleanup, memory summary, final validation.
- Middleware: request/result transformation or execution wrapping.
- Cancel/stop button: external interrupt token, not a hook and not a tool.

Chapter 1 only teaches observer hooks.

## Teaching Order

The chapter order is intentionally not the same as the final package layering.
Teach the ideas in the order learners naturally need them:

```text
Loop -> Tool Calling -> Hooks/Trace -> Harness/Config -> Todo
-> Context Assembly -> Context Compression -> Recovery -> Skills -> Memory
-> RAG Tool -> Agentic RAG -> Research -> Task System
-> Background/Scheduler -> Subagents/Teams -> MCP -> Production/Eval Bridge
```

The foundation track teaches runnable Klara versions. Internal parts of one
mechanism stay together unless splitting them creates a meaningful runnable
chapter. For example, tool schema, registry, metadata, execution, tool errors,
and serial/parallel planning all belong to the tool-calling chapter.

Permission is not an early standalone chapter. It starts as tool metadata and
hook placement, then becomes concrete when external tools, background work,
teams, MCP, and production boundaries create real approval pressure.

Advanced training topics live in labs after the foundation track:

```text
Trace Dataset -> Tiny Pretrain -> Tool-Use SFT -> Preference/DPO
-> MoE Router -> RAG Optimization -> Memory/RL Policy
```

## Tool Package Layout

Each concrete model-visible tool lives in its own package under
`src/klara/capabilities/tools/`:

```text
src/klara/capabilities/tools/
  current_time/
    __init__.py
    schema.py
    timezones.py
    tool.py
```

Use this package shape by default:

- `schema.py`: model-visible `ToolSpec` and Klara-visible `ToolMetadata`.
- `tool.py`: the `KlaraTool` implementation and narrow execution method.
- focused helper files: parsing, normalization, adapters, or domain helpers.
- package `__init__.py`: export the concrete tool class only.

Concrete tools may import `klara.core` contracts and capability-local helpers.
They must not import the loop, backend, frontend, or trace sinks. External
provider clients belong in `src/klara/services/`; the tool package should wrap
that service into a model-visible capability.

## Documentation Hygiene

Keep `docs/skills/` small and current. These files are the compact project
source of truth for future agents and collaborators.

Active project rule files should remain:

```text
architecture.md
roadmap.md
coding-conventions.md
readme-conventions.md
```

Chapter teaching belongs in `docs/chapters/`. Generated or hand-made chapter
images belong in `docs/assets/`.

Archive stale discovery/reports only if they are still worth keeping:

```text
docs/archive/YYYY-MM-DD/<slug>.md
```

Delete stale planning drafts when their useful decisions have already been
promoted into these four files.

Clean project docs after finishing a chapter, changing folder boundaries,
introducing a runtime layer, renaming public concepts, or before merging the
Klara route branch.
