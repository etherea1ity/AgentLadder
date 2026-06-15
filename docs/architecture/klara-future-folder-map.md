# Klara Future Folder Map

This is the target layout for the rebuilt Klara route. It is intentionally a map, not code.

## Repository Identity

```text
AgentLadder/        curriculum repository
Klara               product/persona/runtime built inside the curriculum
src/klara/          future runtime package
docs/chapters/      teaching sequence
docs/architecture/  architecture contracts and decisions
```

## Target Source Layout

```text
src/klara/
  core/
    messages.py
    tools.py
    events.py
    hooks.py
    policies.py
    tool_executor.py
    loop.py
    state.py
    result_builder.py

  app/
    harness.py
    turn_state.py
    context_builder.py
    prompt_loader.py
    tool_loader.py

  context/
    budget.py
    priority.py
    micro_compact.py
    compaction/
      contracts.py
      pipeline.py
      compressor.py
      store.py

  capabilities/
    profiles.py
    selection.py
    registry.py
    tools/
      clock/
      calculator/
      clarify/
      knowledge/
      memory/
      skills/
      web/
      mcp/

  services/
    knowledge/
    rag/
    papers/
    web/
    mcp/
    evidence/
    users/

  memory/
    lifecycle.py
    manager.py
    providers/
    profile/
    durable/
    events/
    retrieval/
    background/

  skills/
    contracts.py
    store.py
    composite.py
    builtin/
    background/

  prompts/
    persona.md
    response_style.md
    tool_policy.md
    runtime_context.md

  background/
    post_turn/
    scheduler.py

  backend/
    api/
    chat/
    streaming/
    trace.py

  eval/
    datasets.py
    scorers.py
    rubrics.py
    reports.py
    failure_taxonomy.py

  training/
    preference_data.py
    reward.py
    policy_eval.py
    optimizers.py
```

## Chapter 1 Minimal Subset

Chapter 1 should not create the whole tree. It should implement only the minimum subset:

```text
src/klara/core/
  messages.py
  tools.py
  events.py
  hooks.py
  policies.py
  tool_executor.py
  loop.py

src/klara/app/
  harness.py

src/klara/capabilities/
  registry.py
  tools/
    fake_tool.py

src/klara/prompts/
  persona.md

docs/chapters/
  ch01-minimal-agent-loop.md
```

## Boundary Rules

`src/klara/core` may import:

- Python standard library
- core-local modules
- type protocols

`src/klara/core` may not import:

- app
- context
- capabilities concrete tools
- services
- memory
- skills
- backend
- eval
- training

`src/klara/app` may import:

- core
- context
- capabilities
- prompts
- memory provider interfaces

`src/klara/capabilities/tools/*` may import:

- core tool contracts
- service contracts
- its own prompt guidance

Concrete services live under `src/klara/services/*`.

Backend and UI should receive public events and trace summaries, not raw prompts, private memory content, raw tool arguments, or private evidence bodies.

## Runtime Data Layout

Local runtime artifacts should stay outside source:

```text
.klara/
  traces/
    <run-id>.jsonl
  users/
    <user-key>/
      messages.jsonl
      profile.json
      memory.json
      events.jsonl
      session_summary.json
      skills/
  indexes/
  eval/
```

These are local adapters. Production storage may replace them without changing the loop.

