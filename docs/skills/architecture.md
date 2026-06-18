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
- concrete tools
- context
- memory
- skills
- services
- backend
- eval
- training

If a later tool or capability needs to affect a run, attach it through app assembly, hooks, tools, context, trace, or service adapters. Do not turn core into a product pipeline.

## Layer Responsibilities

- `app`: assemble persona, user context, model choice, visible tools, hooks, trace sinks, and loop policy.
- `tools`: register, describe, group, filter, and execute model-visible tools.
- `context`: runtime date anchors, prompt-facing message timestamps, budget,
  priority, compaction, summaries, next-turn preparation.
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
`src/klara/tools/builtin/`:

```text
src/klara/tools/builtin/
  current_time/
    __init__.py
    schema.py
    timezones.py
    tool.py
```

Use this package shape by default:

- `schema.py`: model-visible `ToolSpec` and Klara-visible `ToolMetadata`.
- `tool.py`: the `BaseTool` implementation and narrow
  execution method.
- focused helper files: parsing, normalization, adapters, or domain helpers.
- package `__init__.py`: export the concrete tool class only.

`BaseTool` is an authoring helper for local built-in tools, not the runtime
contract. The loop and executor should depend on the structural `KlaraTool`
protocol from `src/klara/core/tools.py`; `BaseTool` only shares argument
validation and observation-building helpers for concrete local packages. This
keeps the path open for future remote, MCP, sandboxed, or generated tools that
implement the protocol without inheriting the local template.

Concrete tools may import `klara.core` contracts and tool-local helpers.
They must not import the loop, backend, frontend, or trace sinks. External
provider clients belong in `src/klara/services/`; the tool package should wrap
that service into a model-visible capability.

Tool registration is automatic for local built-in tools: each package under
`src/klara/tools/builtin/` must expose exactly one `BaseTool` subclass from
`tool.py`. The registry discovers packages, filters visibility later by profile,
and must not carry a hand-written list of default tool instances.

Tool contracts and tool-use policy are separate:

- model-visible capability schema lives in `ToolSpec`
- `ToolSpec.description` should be short: what the tool does and what it returns
- do not put few-shot examples, keyword routing, source-ranking policy, or
  chapter-specific teaching text inside a tool schema
- runtime policy lives in `ToolMetadata`
- general tool-use discipline lives in `src/klara/prompts/persona.md` and
  `src/klara/context/runtime.py`
- execution remains a narrow `run(arguments)` method

Web evidence has runtime guards because prompt text alone was not reliable
enough for current/news/sports questions:

- `web_search` returns candidate snippets only, with `evidence_status` and
  `source_tier` fields on each result.
- If a model tries to answer after candidate snippets without `web_fetch`,
  `WebEvidenceGuard` injects a `runtime_tool_guard` through the loop's
  `final_answer_guard` extension point.
- If search found a `preferred_source` URL but only candidate pages were
  fetched, `WebEvidenceGuard` injects a `runtime_preferred_source_guard`.
- If both preferred and candidate pages were fetched, `WebEvidenceGuard`
  injects a `runtime_source_guard` and masks candidate page text before final
  synthesis.
- If fetched page text is available and no stronger source guard applies,
  `WebEvidenceGuard` injects a `runtime_web_synthesis_guard` so stale schedule
  copy, navigation text, and ads are not treated as the latest report.
- These guards are source-state policies, not intent routers or keyword rules.

Tool execution uses metadata-driven waves:

- consecutive `parallel_safe=True` calls may run in the same wave
- `parallel_safe=False`, approval-gated, or unknown calls split the wave
- result observations keep the original model request order
- dependency planning must use metadata and profiles, not concrete tool names

Core loop and frontend must not branch on concrete tool names.

## Runtime Context And Timestamps

Klara stores raw messages in the app store, then translates them into
model-visible context at the LLM boundary.

Use this split:

- `MessageRecord.created_at`, run timestamps, and event timestamps are audit/UI
  facts. Keep them in UTC ISO form.
- `src/klara/context/runtime.py` builds the date-only runtime context appended
  to the system prompt.
- `src/klara/context/timestamps.py` builds compact user-message prefixes from
  each message's own creation timestamp.
- `apps/api/services/run_service.py` is the API boundary that converts stored
  messages into model-visible `KlaraMessage` content.

Do not write timestamp prefixes back into stored user content. Do not stamp
assistant or tool messages. Do not use current wall-clock time to restamp
historical messages; replayed history must derive from each message's own
`created_at` so it stays stable.

The system prompt should include the current date and timezone but avoid
minute-level time. Exact wall-clock questions belong to the `current_time` tool.

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
