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
    user_context.py

  workspace/
    bootstrap.py
    context_files.py
    profile_loader.py
    templates/
      IDENTITY.md
      USER.md
      PROJECT.md
      MEMORY.md

  sessions/
    transcript.py
    window.py
    summary.py
    compaction.py
    searchable_history.py
    store.py

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
    users/
    knowledge/
    rag/
    papers/
    web/
    mcp/
    evidence/
    storage/

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
    routines.py
    triggers/
      cron.py
      webhook.py
      api.py
    delivery/
      local.py
      webhook.py

  safety/
    permissions.py
    prompt_injection.py
    external_content.py
    path_guard.py
    redaction.py

  resilience/
    retry.py
    fallback.py
    loop_guard.py
    truncation.py
    recovery.py

  plugins/
    manifests.py
    discovery.py
    resources.py
    adapters.py

  backend/
    api/
    chat/
    users/
    sessions/
    streaming/
    trace.py

  infra/
    config/
    llm/
    observability/
    storage/

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
  user_context.py

src/klara/capabilities/
  registry.py
  tools/
    fake_tool.py

src/klara/prompts/
  persona.md

docs/chapters/
  ch01-minimal-agent-loop.md
```

Chapter 1 can use a local default user context. It should not teach auth,
tenancy, accounts, or production user management.

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
- user-context contracts
- memory provider interfaces
- workspace/profile bootstrap contracts
- session store interfaces

`src/klara/capabilities/tools/*` may import:

- core tool contracts
- service contracts
- its own prompt guidance

Concrete services live under `src/klara/services/*`.

`src/klara/workspace` owns readable bootstrap material: persona-adjacent files,
project context, user-facing profile hints, and memory summaries prepared for
prompt assembly. It should not own raw long-term memory.

`src/klara/sessions` owns transcripts, message windows, summaries, compaction
artifacts, and searchable history references. It should not call models or
execute tools.

`src/klara/safety` owns permissions, redaction, external-content labeling,
prompt-injection checks, and path guards.

`src/klara/resilience` owns retries, fallback, loop guards, truncation behavior,
and recovery plans.

`src/klara/plugins` is a late-stage extension boundary for manifests, external
resource declarations, and adapter loading. It is not part of the early loop.

Backend and UI should receive public events and trace summaries, not raw prompts, private memory content, raw tool arguments, or private evidence bodies.

## User And Session Boundary

Klara should have user partitioning in the final architecture, but it should not
dominate the early teaching chapters.

The recommended model is:

```text
UserContext
  user_id          stable internal identity
  display_name     prompt-visible, optional, not unique
  locale           optional prompt/runtime hint
  timezone         optional prompt/runtime hint
  storage_key      filesystem/database partition key
```

Early chapters may use:

```text
UserContext.local_default()
```

This keeps Chapter 1 and Chapter 2 focused on loop and harness while still
preventing later rewrites when memory, sessions, skills, eval traces, and
production auth arrive.

User management ownership:

```text
src/klara/app/user_context.py      runtime identity contract
src/klara/services/users/          user lookup and local user adapters
src/klara/backend/users/           HTTP/auth-facing user binding
src/klara/backend/sessions/        session history and session lifecycle
src/klara/infra/storage/           filesystem/database adapters
```

Rules:

- Core loop never knows user accounts.
- Harness receives a `UserContext`.
- Memory, skills, session history, and traces are partitioned by `storage_key`.
- Display name can enter prompts; storage keys and private identifiers should not.
- Production auth belongs to the Production Runtime chapter, not Chapter 1.

## Runtime Data Layout

Local runtime artifacts should stay outside source:

```text
.klara/
  traces/
    <run-id>.jsonl
  sessions/
    <session-id>/
      transcript.jsonl
      summary.json
      compaction.jsonl
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

## Teaching Versus Final Architecture

The final architecture needs user/session/storage boundaries from the beginning,
because memory, skills, trace datasets, and eval all become user- or project-
scoped later.

The teaching path should reveal that boundary gradually:

```text
Chapter 1: default local user only
Chapter 2: UserContext contract appears in Harness
Chapter 6: memory uses user partitioning
Chapter 7: skills use user/project partitioning
Chapter 11: routines use restricted user/project capability profiles
Chapter 14: auth, accounts, storage adapters, and production session management
```

This keeps the early learning path simple without designing a dead-end runtime.
