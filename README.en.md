# Chapter 3: Hooks and Trace

Language: [中文](./README.md) | English

Previous: [Chapter 2: Tool Calling](./docs/chapters/ch02-tool-calling.en.md)

Next: Chapter 4: Harness And Config

Roadmap: [Klara Roadmap](./docs/skills/roadmap.md)

Full chapter: [docs/chapters/ch03-hooks-and-trace.en.md](./docs/chapters/ch03-hooks-and-trace.en.md)

---

## The Chapter In One Sentence

Klara does not turn the loop into a black-box function; it emits public events at key lifecycle points, hooks can observe or lightly influence those events, and trace, API, and the frontend run surface are all projections from the same event stream.

![Klara Chapter 3 Hooks and Trace](./docs/assets/ch03-hooks-and-trace.svg)

| What you see | What Klara does |
| --- | --- |
| `user_prompt_submit.*` | The user request enters runtime, and hooks can observe the submit boundary |
| `llm.started/completed` | A model call starts/ends, and trace plus UI update from the same event |
| `pre_tool_use.*` | A hook placement runs before a tool; it can allow/block, but it is not a full permission engine |
| `tool.started/completed/failed` | Every tool call has pairable started and terminal events |
| `post_tool_use.*` | After the tool observation exists, hooks can observe the result |
| `stop.*` | The loop is about to stop, and hooks can observe cleanup |
| JSONL trace | Developers can replay the public lifecycle of a run |
| frontend run surface | Users can see tool cards and runtime status |

## Quick Experience

Start backend and frontend:

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

You should see a run surface under the assistant message with a model call, a `current_time` tool card, hook placement badges, and trace state after completion.

Then open:

```text
http://127.0.0.1:8011/api/runs/{run_id}
```

You should see the same run events. After deleting the session, related messages, runs, events, and JSONL trace lines are purged.

## 1. What Chapter 3 changes

The Chapter 2 tool loop already works:

```text
model produces tool_calls
-> runtime executes tools
-> observations return to the next model turn
```

Chapter 3 does not rewrite that loop. It adds a lifecycle event stream:

```text
KlaraLoop
-> public KlaraEvent
-> HookManager
-> JsonlTraceHook / RunEventProjector / frontend run surface
```

Klara learns: if runtime behavior needs to be observed or lightly influenced, that logic should not be stuffed into the loop body. It should attach to stable placements and project stable public events.

Code:

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
```

## 2. Public events are the shared source of truth

`KlaraEvent` is the shared source for trace, API, and UI. It contains:

```text
schema_version
event_id
seq
type
run_id
timestamp
payload
private_payload_ref
```

`seq` starts at 1 and increases monotonically within a run. `payload` remains compatible with older call sites, while the newer public boundary is expressed by `public_payload`. Tool results expose compact preview and length concepts, so UI does not display long raw tool content as answer text.

Code:

```text
src/klara/core/events.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

Reader takeaway: a public event is not casual logging; it is a replayable, projectable, testable runtime contract.

## 3. Hooks are lifecycle extension points, not tools

This chapter has two hook behaviors:

```text
observer hook
-> on_event(event)
-> observe only

placement hook
-> on_user_prompt_submit / on_pre_tool_use / on_post_tool_use / on_stop
-> observe or lightly decide at fixed lifecycle positions
```

PreToolUse can block the current tool call, but it is still not a full permission engine. A block produces:

```text
pre_tool_use.completed allowed=false
tool.failed blocked=true
failed observation enters the next model turn
```

It does not open an approval UI, wait for human confirmation, write durable policy, or mutate the tool registry.

Code:

```text
src/klara/core/hooks.py
src/klara/core/loop.py
tests/klara/core/test_hooks.py
```

## 4. Tool lifecycle events pair exactly

Every tool call has teachable event semantics:

```text
successful tool  -> one tool.started + one tool.completed
unknown tool     -> one tool.started + one tool.failed
tool exception   -> one tool.started + one tool.failed
PreToolUse block -> zero tool.started + one tool.failed
policy stop      -> pending call does not produce tool.started
```

This lets the run surface render reliable tool cards, and it lets trace replay avoid guessing whether a tool actually executed.

Code:

```text
src/klara/core/loop.py
src/klara/tools/executor.py
tests/klara/core/test_loop.py
```

## 5. Trace and frontend are two projections

JSONL trace is the developer view:

```json
{
  "schema_version": 1,
  "event_id": "evt_...",
  "seq": 7,
  "type": "tool.completed",
  "run_id": "run_...",
  "payload": {
    "tool_result": {
      "name": "current_time",
      "ok": true,
      "content_preview": "...",
      "content_length": 128
    }
  }
}
```

API/SSE is the product view:

```text
llm.started         -> llm_call_started
tool.started        -> tool_call_started
tool.failed         -> tool_call_failed
pre_tool_use.*      -> hook_placement_*
tool_policy.stopped -> policy_stop
```

The frontend run surface is the user view:

```text
compact lifecycle timeline
tool cards
hook badges
trace saved state
optional workstream note
```

Code:

```text
apps/api/services/run_event_projector.py
apps/api/services/app_store.py
apps/api/services/run_service.py
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
```

## 6. Optional narrator is only a capstone

The narrator model is default-off and lives only in the API/app projection layer. It does not write assistant content, does not enter future main-model messages, and does not reveal raw chain-of-thought.

It can only generate short notes from real run events:

```text
workstream_note
-> text
-> source=narrator_model
-> phase
-> evidence_event_ids
```

If it claims search, reading, running, verification, or edits, recent events must support that claim. Invalid JSON, unsupported claims, duplicates, overlong text, or hidden-reasoning language are ignored.

Code:

```text
apps/api/services/workstream_narrator.py
src/klara/prompts/workstream_narrator.md
tests/apps/api/test_workstream_narrator.py
```

## What This Chapter Does Not Do

Chapter 3 does not include:

- complete permission engine
- Todo Planning
- agent task ledger
- context compression
- memory write policy
- full harness/config refactor
- full provider streaming adapter
- OpenAI/Claude/DeepSeek reasoning stream integration
- raw chain-of-thought display

Todo belongs to Chapter 5. RAG/module pipelines belong to later chapters. The Thinking-like narrator is only an evidence-bound runtime note, not the main line of Chapter 3.

## Code Index

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
apps/api/services/run_event_projector.py
apps/api/services/app_store.py
apps/api/services/run_service.py
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
```

## Run And Verify

Backend and core:

```powershell
pytest -q
```

Frontend:

```powershell
cd apps\web
npm test
npm run build
npm audit --omit=dev
```

Suggested manual check:

1. Start `.\scripts\dev.ps1`.
2. Ask a `current_time` question.
3. Inspect tool cards and hook badges in the run surface.
4. Open `/api/runs/{run_id}` and inspect events.
5. Delete the session and confirm related trace data is purged.

## Small Experiments

1. Write a hook that only implements `on_event`, and confirm it receives lifecycle events.
2. Write an `on_pre_tool_use` hook that returns `allowed=False`, and confirm the tool does not execute while the model sees a failed observation.
3. Make a hook raise, and confirm the run still completes.
4. Open the JSONL trace and replay one run by `seq`.

## Next Chapter

Chapter 4 covers Harness And Config: now that loop, tools, hooks, and trace have boundaries, the next step is assembling provider, model, prompt, tools, hooks, and trace sink through one clear harness entry point.
