# Klara Coding Conventions Reference

Klara code is teaching code and real engineering code at the same time.

## Naming

Use `Klara` prefix only for public runtime concepts:

```text
KlaraLoop
KlaraMessage
KlaraEvent
KlaraTool
KlaraHarness
KlaraRunResult
```

Use direct domain names for helpers:

```text
ToolExecutor
HookManager
LoopPolicy
UserContext
CapabilityRegistry
```

Rules:

- Files use lowercase snake case: `loop.py`, `tool_executor.py`, `user_context.py`.
- Classes use PascalCase.
- Functions, methods, and variables use snake_case.
- Constants use UPPER_SNAKE_CASE.
- Boolean names should read like predicates: `is_visible`, `should_continue`, `has_tool_calls`.
- Collections use plurals: `messages`, `tool_calls`, `events`.
- Avoid vague names like `data`, `item`, `obj`, `utils.py`, `helpers.py`, `common.py`.

## Folder Boundaries

`src/klara/core` may contain only runtime mechanics:

```text
messages.py
tools.py
events.py
hooks.py
policies.py
tool_executor.py
loop.py
```

Core additions must pass all three checks:

1. Does it still make sense in a no-RAG, no-memory, no-backend loop?
2. Can it be tested without app/services/storage?
3. Does it define a runtime contract later layers need?

If not, put it outside core.

Concrete model-visible tools are packages, not flat files:

```text
src/klara/capabilities/tools/<tool_name>/
  __init__.py
  schema.py
  tool.py
```

Add helper files inside the tool package when they make one concern easier to
teach, such as `timezones.py`, `query.py`, or `result_parser.py`. Do not create
generic `utils.py`, `helpers.py`, or `common.py`.

## Comments And Docstrings

Klara uses high teaching density:

- Every module has a module docstring.
- Every class has a class docstring.
- Every public function/method has a docstring.
- Important state variables have comments or self-explanatory names/types.
- Every `for` / `while` loop has one comment explaining loop intent.
- Each key phase has a comment explaining why it happens now.

Class docstrings should answer:

- What does this class own?
- What does it not own?
- Which layer does it belong to?
- Which boundary will later chapters use to extend it?

Public function docstrings should use `Args` and `Returns`; add `Raises` for meaningful business errors.

## Code Shape

- Prefer explicit dependency injection over hidden globals.
- Prefer protocols for injected boundaries.
- Keep public payloads safe for trace/UI.
- Do not leak secrets, private prompts, raw hidden context, or chain-of-thought into trace.
- Use dataclasses/Pydantic-style contracts where structured state matters.
- Keep chapter code small but real enough to test and run.
- Do not put chapter numbers, branch names, release numbers, or roadmap positions
  into runtime identifiers, storage keys, API responses, class names, method names,
  comments, or UI labels. Those labels belong in docs and chapter navigation only.
- Package-manager metadata may keep required package versions; runtime contracts
  should expose capabilities and schema ids, not course-version labels.

## Imports

`src/klara/core` may import only:

- Python standard library
- core-local modules
- typing protocols

It may not import app, capabilities concrete tools, services, memory, skills, backend, eval, or training.

## Tests

Test names should read like behavior:

```text
test_one_tool_run_feeds_observation_back_to_model
test_core_does_not_import_future_layers
```

Use:

- focused unit tests for contracts and loop behavior
- architecture tests for import boundaries
- trace/event assertions when observability changes
- minimal integration tests for harness/provider/API wiring

Run targeted tests first, then broader checks when the change touches shared boundaries.
