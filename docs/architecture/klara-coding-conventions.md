# Klara Coding Conventions

These conventions keep Klara teachable. The code should read like a curriculum
and still behave like a real runtime.

## Naming

Use Klara names for public runtime concepts:

- `KlaraLoop`
- `KlaraMessage`
- `KlaraEvent`
- `KlaraTool`
- `KlaraHarness`
- `KlaraRunResult`

Use plain domain names for internal helpers:

- `ToolExecutor`
- `HookManager`
- `LoopPolicy`
- `UserContext`
- `CapabilityRegistry`

Avoid vague agent names:

- do not use `Agent`, `Runner`, or `Manager` alone when the boundary is more
  specific
- prefer `KlaraHarness` over `AgentRunner`
- prefer `ToolExecutor` over `ToolManager`

File and module names use lowercase snake case:

```text
loop.py
tool_executor.py
user_context.py
fake_tool.py
```

Class names use PascalCase. Functions, methods, variables, and test names use
snake_case.

Test names should state behavior:

```text
test_one_tool_run_feeds_observation_back_to_model
test_core_does_not_import_future_layers
```

## Folder Rules

`src/klara/core` is for runtime mechanics only:

- messages
- tool contracts
- events
- hooks
- loop policy
- tool execution boundary
- loop execution

`src/klara/app` assembles a run:

- persona prompt
- user context
- model choice
- visible tools
- trace hook
- loop policy

`src/klara/capabilities` owns registered abilities:

- fake Chapter 1 tools
- later chapter tools
- capability profiles
- visibility selection

Later folders must not be imported into `core`:

- `context`
- `services`
- `memory`
- `skills`
- `backend`
- `eval`
- `training`

If a later feature needs the loop, attach it through app, hooks, capabilities,
context, or trace. Do not expand core into a product pipeline.

## Core Size Rule

Core is allowed to have several small files. The problem is not file count; the
problem is responsibility creep.

Chapter 1 core file whitelist:

```text
__init__.py
messages.py
tools.py
events.py
hooks.py
policies.py
tool_executor.py
loop.py
```

A new core file is allowed only when it describes a runtime invariant that is
independent of RAG, memory, skills, backend, UI, eval, and production services.

Before adding a core file, ask:

1. Would this still make sense in a no-RAG, no-memory, no-backend loop?
2. Can this be tested without app, services, or storage?
3. Does this define a contract that later layers depend on?

If the answer is not yes to all three, the file belongs outside core.

## Comments

Prefer self-explanatory names over comments.

Use comments when they protect architecture:

```python
# Core records the tool request but does not know concrete capability profiles.
```

Use comments when a block is intentionally narrow:

```python
# Chapter 1 keeps preparation as an identity transform; compression arrives later.
```

Avoid comments that repeat the line:

```python
# Bad: Set the model.
model = "fake-model"
```

Do not put roadmap explanations in code comments. Put curriculum reasoning in
chapter docs.

## Docstrings

Module docstrings should be short and boundary-focused.

Good:

```python
"""Core loop contracts for Klara."""
```

Avoid long product stories in source files. The story belongs in `docs/`.

## Tests

Every chapter should include:

- behavior tests for the new capability
- at least one architecture/boundary test when a new layer appears
- fake providers instead of real network calls
- deterministic trace or event assertions when observability changes

Tests should protect teaching boundaries, not only output strings.

## Style

- Prefer dataclasses and protocols for Chapter 1 contracts.
- Prefer explicit return objects over loose dictionaries at public boundaries.
- Prefer tuples for immutable message/tool/event collections.
- Keep public payloads serializable.
- Do not introduce dependencies unless the chapter needs them.
- Do not add real I/O to core except through injected protocols or hooks.
