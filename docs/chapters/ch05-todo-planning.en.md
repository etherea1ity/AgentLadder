# Chapter 5: Todo Planning

Language: [Chinese](./ch05-todo-planning.md) | English

Previous: [Chapter 4: Harness and Config](./ch04-harness-and-config.en.md)

Next: [Chapter 6: System Prompt and Context Assembly](../skills/roadmap.md#chapter-6---system-prompt-and-context-assembly)

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## Understand This Chapter in One Sentence

Klara turns a multi-step task plan into versioned, schema-validated current-session state; one model `todo_write` update reaches the same JSONL trace, SSE stream, refresh recovery path, and plan panel.

![Klara Chapter 5 Todo Planning](../assets/ch05-todo-planning.svg)

| User task | Planning behavior |
| --- | --- |
| Simple answer or one-step request | Answer directly without an unnecessary plan |
| Multi-step tool work | Create the plan before substantive work |
| Work advances or scope changes | `merge` in place or `replace` the ordered plan |
| Completion claim | Mark verified steps `completed` only after evidence exists |

## Quick Experience

Start the local product:

```powershell
.\scripts\dev.ps1
```

Submit an explicitly multi-step task such as:

```text
Inspect the repository, fix the failing test, run the relevant suite, and write a short report.
```

When the model chooses to plan, the chat displays the current plan, completion progress, and version. The plan survives a refresh and is removed with its conversation. A simple question should not generate a plan merely to demonstrate the feature.

## Why a Natural-Language Plan Is Not Enough

A prose list is readable but cannot reliably answer which step is active, whether one update overwrote another, whether refresh restored the same state, whether the model claimed success before verification, or whether the UI and trace show the same change.

Chapter 5 therefore separates planning into three layers:

```text
TodoItem  -> one stable step and status
TodoPlan  -> an ordered, versioned current-session snapshot
todo_write -> the model-callable replace / merge boundary
```

## Mechanism One: The State Machine Rejects Strange Plans Before Writing

`TodoItem` accepts only a stable lowercase id, a non-empty title, and `pending`, `in_progress`, or `completed`. `TodoPlan` contains at most 24 unique steps and enforces no more than one `in_progress` item.

<details>
<summary>Inspect the real contract</summary>

```text
src/klara/planning/todo.py
src/klara/planning/tool.py
tests/klara/planning/test_todo.py
tests/klara/planning/test_tool.py
```

An invalid update becomes a model-visible failure observation instead of partially writing state or crashing the Agent loop.

</details>

## Mechanism Two: Replace and Merge Are Deterministic and Reproducible

`replace` uses input order to create the complete next snapshot. `merge` is an ordered upsert: an existing id updates in place, while a new id appends in input order. Every successful update strictly increments the version.

```text
v4: [inspect(done), build(active)]
merge: [build(done), verify(active)]
v5: [inspect(done), build(done), verify(active)]
```

Update derivation and the JSONL append occur under one reentrant lock, so concurrent updates receive distinct monotonic versions instead of deriving from the same stale snapshot.

## Mechanism Three: A Plan Belongs to a Session, Not One Model Call

The API constructs a `TodoWriteTool` bound to the current `session_id` for each run. Storage returns only the latest plan for a visible session; page refresh restores it through `SessionDetail.todo_plan`. Deleting a conversation also removes its messages, runs, events, traces, and todo plan.

<details>
<summary>Inspect the persistence boundary</summary>

```text
apps/api/services/app_store.py
apps/api/services/run_service.py
apps/api/routes/sessions.py
tests/apps/api/test_todo_planning.py
```

The CLI exposes `todo_write` through the same harness, but its teaching path keeps the plan only for the current process. Product session recovery belongs to the API JSONL store.

</details>

## Mechanism Four: One Update Produces Two Verifiable Projections

The core `tool.completed` trace stores the full public `todo_write` plan observation, so the tool fact is replayable. The product layer validates `TodoPlan` from that same observation and emits a `todo_plan_updated` SSE event. The frontend neither guesses state nor parses checkboxes from prose.

```text
todo_write result
├─ JSONL trace: tool.completed.payload.tool_result.content
└─ API/SSE: todo_plan_updated.payload
   ├─ live React state
   └─ accessible Plan panel
```

## Mechanism Five: The Plan UI Shows Progress Without Taking Over the Chat

The plan panel sits at the top of the message scroller and shows order, status, completion ratio, and version. It does not expose the `session_id` or internal item ids. Narrow screens hide redundant status words while preserving markers and titles; dark mode uses the same design tokens.

<details>
<summary>Inspect the frontend data path</summary>

```text
apps/web/src/types/domain.ts
apps/web/src/api/client.ts
apps/web/src/App.tsx
apps/web/src/components/ChatWorkspace.tsx
apps/web/src/components/PlanPanel.test.tsx
apps/web/src/App.e2e.test.tsx
```

Restore and live-SSE tests cover refresh and in-run updates separately; browser evidence covers desktop and narrow layouts.

</details>

## Run and Verify

```powershell
$env:PYTHONPATH = "src;."
python -m klara.eval.chapter05_cli `
  --repository-root . `
  --json-out docs/reports/product/ch05-todo-planning.json `
  --markdown-out docs/reports/product/ch05-todo-planning.md `
  --markdown-en-out docs/reports/product/ch05-todo-planning.en.md
python -m pytest -q
Push-Location apps/web
npm test
npm run build
Pop-Location
```

The machine gate uses the real `RunService -> KlaraHarness -> todo_write -> store -> projection` product path. It does not treat a hand-authored successful result as capability evidence. The behavior-evaluation control probe still validates only the evaluation substrate and cannot claim GPT-level product quality.

## Small Experiments

1. Create two `in_progress` steps and confirm that the tool returns a failure observation while the previous plan remains unchanged.
2. `merge` an existing step and confirm that it updates in place while only new steps append.
3. Refresh and confirm the version is unchanged, then delete the conversation and verify its record is gone from `todo_plans.jsonl`.
4. Submit a one-sentence definition question and confirm persona guidance leads the model to answer directly without abusing `todo_write`.

## Chapter Boundary

This chapter prevents current-session drift only. Restart-safe dependency graphs, claims and leases, retries, scheduling, and multi-Agent coordination belong to Chapters 14–16. Wrapping Todo as those capabilities would create a false completion claim.

## Next Chapter Preview

Chapter 6 assembles persona, history, tool guidance, runtime state, and budgets into an explicit context contract. Chapter 7 handles compression and recovery after that context genuinely exceeds its window.
