# Chapter 3: Hooks and Trace

Language: [Chinese](./README.md) | English

Previous: [Chapter 2: Tool Calling](./docs/chapters/ch02-tool-calling.en.md)

Next: Chapter 4: Harness And Config

Roadmap: [Klara Roadmap](./docs/skills/roadmap.md)

Full chapter: [docs/chapters/ch03-hooks-and-trace.en.md](./docs/chapters/ch03-hooks-and-trace.en.md)

---

## The Chapter In One Sentence

Klara emits public lifecycle events instead of hiding the loop in a black box; hooks, JSONL trace, API/SSE, the GPT-style thinking block, and the developer trace panel all project from that same event stream.

![Klara Chapter 3 Hooks and Trace](./docs/assets/ch03-hooks-and-trace.svg)

| What you see | What Klara does |
| --- | --- |
| Hooks | Observes lifecycle events and runs fixed placements such as `PreToolUse` |
| Trace | Records public events plus duration and token metrics |
| Thinking block | Shows `Thinking...`, then `Thought for Xs`, with a chevron-expanded summary |
| Developer trace | Keeps tool cards, hook badges, and raw run status out of the answer text |
| Web evidence | Treats search as candidates, fetch as evidence, and fixtures as not results |

## Quick Experience

Start the app:

```powershell
.\scripts\dev.ps1
```

Open:

```text
http://127.0.0.1:5123
```

Ask:

```text
Please use current_time to check the current time in Asia/Shanghai, then answer in one sentence.
```

Expected visible behavior:

```text
Thinking...  -> public event stream while active
Thought for Xs -> right-side chevron expands the trace-grounded details
Assistant answer -> only answer_delta changes message content
Developer trace -> tool cards, hook badges, trace saved state, metrics
```

Inspect the run:

```text
http://127.0.0.1:8011/api/runs/{run_id}
```

Deleting a session also purges related messages, runs, events, and JSONL trace lines.

## What Chapter 3 Adds

Chapter 2 made tool calling work:

```text
model tool_calls -> runtime executes tools -> observations return to model
```

Chapter 3 adds public lifecycle structure around that loop:

```text
KlaraLoop
-> KlaraEvent
-> HookManager
-> JsonlTraceHook
-> RunEventProjector
-> frontend thinking block + developer trace
```

The core point is not a decorative UI. The core point is a stable event contract that can be observed, traced, projected, tested, and later reused for evaluation.

## Hooks

Hooks have two jobs:

```text
observer hook   -> on_event(event)
placement hook  -> on_user_prompt_submit / on_pre_tool_use / on_post_tool_use / on_stop
```

`PreToolUse` can block one tool call, but it is not a full permission engine. A block creates a failed tool observation for the next model turn; it does not open an approval UI, wait for a person, or write durable policy.

Hook failures are isolated. They are recorded in `HookManager.failures` and do not crash the run.

## Trace And Metrics

Trace has two layers:

```text
event trace   -> what happened
metrics trace -> how long it took and what usage was reported
```

`llm.completed`, tool terminal events, and `run.completed` expose `duration_ms`, latency, usage totals, and `token_source` where available. `token_source` is `reported`, `estimated`, or `unknown`.

Public payloads are safe projection surfaces. Private payload content is not embedded; future private material is represented only by `private_payload_ref`.

## API/SSE Projection

`RunEventProjector` maps core events into product-facing events:

```text
llm.started   -> llm_call_started
tool.failed   -> tool_call_failed
pre_tool_use  -> hook_placement_*
run events    -> SSE + stored RunEventRecord
```

`answer_delta` is not trace. `thinking_summary_delta` is not assistant content. Both are persisted as run events, but only answer deltas mutate the assistant message.

## Thinking Summary

The visible thinking block is GPT-style:

```text
active:    Thinking... 4.2s
completed: Thought for 23.9s
toggle:   right-side chevron only
```

During the run, the expanded block shows a small stream derived from real public events. After completion, an optional narrator can summarize the completed public trace. If no narrator is configured, Klara does not invent a fake summary.

This is not raw chain-of-thought and not hidden reasoning display.

## Web Evidence Boundary

For current sports and score-like questions:

- search results are candidates, not facts
- snippets do not support concrete scores
- fixtures are not results
- a scheduled match with no fetched verified score is not `0:0`
- official, wire, or sports-media evidence is preferred for current results
- aggregator-only evidence cannot support concrete scores

Teaching demo:

```text
帮我搜一下世界杯最新进展
```

Klara should search, fetch relevant evidence, separate completed results from scheduled or in-progress fixtures, include source URLs, and show `web_search` / `web_fetch` latency in trace.

## Code Index

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
src/klara/tools/executor.py
src/klara/context/web_evidence.py
src/klara/services/web/source_quality.py
apps/api/services/run_event_projector.py
apps/api/services/app_store.py
apps/api/services/run_service.py
apps/api/services/workstream_narrator.py
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
```

## Run And Verify

```powershell
pytest -q
cd apps\web
npm test
npm run build
npm audit --omit=dev
```

Chapter 4 will move this runnable runtime into a clearer Harness And Config boundary.
