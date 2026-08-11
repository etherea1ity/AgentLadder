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
Trace Dataset -> Tiny Pretrain -> Tool-Use SFT/Trajectory Distillation
-> Preference/DPO -> Tiny Sparse MoE -> FP16/FP4 Low Precision
-> RAG Optimization -> Memory/RL Policy
```

Lab artifacts must not move training policy back into the runtime core:

- evaluation and training consume versioned, redacted trace exports
- teacher datasets contain public state/action/observation/final records, never
  provider-hidden reasoning or chain-of-thought
- the custom dense Transformer and sparse MoE live in training/lab modules, not
  under `src/klara/core`
- FP16 execution and FP4 quantization report their actual storage and compute
  paths; emulation must not be presented as native FP4 arithmetic
- CLI, JSON/JSONL, checkpoints, plots, and Markdown reports are sufficient proof
  surfaces; advanced labs do not require new frontend work

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

Runtime must stay free of semantic web guards:

- Core loop does not inspect user intent, keywords, domains, source counts, or
  assistant draft claims to force another tool call.
- `web_search` returns candidate links and snippets in provider order.
- `web_fetch` returns fetched source text and metadata for one public URL.
- Tool selection is model-led through the system prompt and tool schemas.
- Future grounding, ranking, citation, and evaluation work belongs in later
  services or eval layers, not in `src/klara/core` or generic runtime context.
- Protocol and safety rules are still allowed: tool-call/result pairing,
  timeouts, permission hooks, SSRF-safe fetching, final-turn no-tool synthesis,
  and repeated-tool-call limits.

Public activity must also stay layered:

- API projection may derive `activity_fact_recorded` events from public run
  events, but those facts are structured data only.
- Activity facts must not contain user-visible `title` or `body` prose.
- Activity facts may include tool names, result counts, metrics, short previews,
  and `evidence_event_ids`, but not raw arguments, full URLs, full observations,
  secrets, or hidden reasoning.
- User-visible Thinking and Activity Drawer content has three public sources:
  provider reasoning summaries, main-model public commentary, and sanitized
  runtime action transcript.
- Main-model public commentary is emitted as `assistant_activity_delta`. When a
  model response contains both assistant text and tool calls, that text is
  activity commentary, not the final answer.
- Runtime action transcript is compact and factual: tool names, status, counts,
  safe source titles, domains, and evidence ids. It must not be expanded into
  canned natural-language thinking.
- Optional completed-summary enhancers are experimental and off by default.
  They must never replace provider reasoning or main-model commentary, and they
  must not fabricate activity when public evidence is absent.

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
web-research-state-machine.md
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
