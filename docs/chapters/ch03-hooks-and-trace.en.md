# Chapter 3: Hooks and Trace

Language: [中文](./ch03-hooks-and-trace.md) | English

Previous: [Chapter 2: Tool Calling](./ch02-tool-calling.en.md)

Next: Chapter 4: Harness And Config

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## The Chapter In One Sentence

Klara does not turn the loop into a black-box function; it emits public events at key lifecycle points, hooks can observe or lightly influence those events, and trace, API, and the frontend run surface are all projections from the same event stream.

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

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

Ask a stable tool question:

```text
Please use current_time to check the current time in Asia/Shanghai, then answer in one sentence.
```

You should see a run surface under the assistant label with a model call, a `current_time` tool card, hook placement badges, and trace state after completion.

Then open the API run detail:

```text
http://127.0.0.1:8011/api/runs/{run_id}
```

You should see the same run events. After deleting the session, related messages, runs, events, and JSONL trace lines are purged.

## 3.1 Why Chapter 2's tool loop is not enough

Chapter 2 lets the model request tools, lets runtime execute tools, and feeds observations back into context. But at that point the loop still behaves like an opaque function:

```text
user request
-> loop
-> maybe tools
-> final answer
```

When a user asks "why did it not keep searching?" or "which tool was blocked?", scattering more logging through the loop is the wrong shape. Klara needs a stable lifecycle event layer:

```text
loop emits public lifecycle events
-> hooks observe or lightly decide
-> JSONL trace stores public replay data
-> API/SSE projects user-visible events
-> frontend run surface renders tool cards and hook badges
```

Code:

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
apps/api/services/run_event_projector.py
apps/web/src/components/klara/KlaraRunSurface.tsx
```

Reader takeaway: Chapter 3 is not adding UI to the loop; it turns the loop lifecycle into an observable, testable, projectable public event stream.

## 3.2 KlaraEvent: public lifecycle events

`KlaraEvent` is the core contract in this chapter. It turns "something happened inside runtime" into a stable public event.

Two fields define the important boundary:

```text
public_payload      -> trace / API / UI may use it
private_payload_ref -> future reference to private material, without embedding that material
```

Code:

```text
src/klara/core/events.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

<details>
<summary>Expand: how to read KlaraEvent and EventSequencer</summary>

`EventKind` centralizes public event names, while `EventSequencer` assigns monotonically increasing `seq` values within one run.

```python
class EventSequencer:
    def __init__(self) -> None:
        self._next_value = 1

    def next(self) -> int:
        value = self._next_value
        self._next_value += 1
        return value

@dataclass(frozen=True)
class KlaraEvent:
    type: str | EventKind
    run_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    event_id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    seq: int | None = None
    public_payload: dict[str, Any] | None = None
    private_payload_ref: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "seq": self.seq,
            "type": self.type,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "payload": self.public_payload or {},
            **({"private_payload_ref": self.private_payload_ref} if self.private_payload_ref else {}),
        }
```

How to read it:

1. `type` names the lifecycle point, such as `tool.started` or `stop.completed`.
2. `run_id` joins all events from one loop execution.
3. `event_id` gives trace replay, API projection, and tests a stable join key.
4. `seq` is run-local ordering; tests confirm it starts at 1 and increases monotonically.
5. `public_payload` is externally visible; old call sites that pass only `payload` remain compatible.
6. `private_payload_ref` stores only a reference, not private content.

State change: every loop `_emit` creates an event with `event_id` and `seq`; hooks, trace, and API projection all see the same public event.

Boundary: core may expose tool name, tool call id, short preview, and content length, but it should not push future private payloads or full long tool content directly to UI.

</details>

## 3.3 Observer hook: trace should not affect loop correctness

An observer hook is the lightest extension point: it receives events and does not decide loop behavior. `JsonlTraceHook` is an observer.

```text
KlaraLoop._emit(...)
-> HookManager.emit(event)
-> JsonlTraceHook.on_event(event)
-> event.to_public_dict() is written to JSONL
```

Code:

```text
src/klara/core/hooks.py
apps/api/services/app_store.py
tests/apps/api/test_app_store_delete.py
```

This chapter fixes the teaching boundary of trace shape: each JSONL line uses top-level `run_id`, so app-store lookup and purge also use `record.get("run_id")`. Deleting a session therefore removes related trace lines instead of leaving orphan trace data.

Reader takeaway: trace is the developer-facing public lifecycle record; it should not decide whether the loop succeeds.

## 3.4 Lifecycle placement: UserPromptSubmit / PreToolUse / PostToolUse / Stop

The main line of Chapter 3 is not "permissions"; it is placement. Klara gives hooks stable entry points at important lifecycle positions:

```text
user prompt enters runtime -> UserPromptSubmit
before a tool executes     -> PreToolUse
after tool observation     -> PostToolUse
before run completed       -> Stop
```

Code:

```text
src/klara/core/hooks.py
src/klara/core/loop.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

<details>
<summary>Expand: HookManager's minimal decision model</summary>

This chapter introduces one small decision object:

```python
@dataclass(frozen=True)
class HookDecision:
    allowed: bool = True
    reason: str = ""
    public_metadata: dict[str, object] = field(default_factory=dict)
```

`HookManager` still supports observer hooks:

```python
def emit(self, event: KlaraEvent) -> None:
    for hook in self._hooks:
        try:
            hook.on_event(event)
        except Exception as exc:
            self.failures.append((event.type, f"{type(exc).__name__}: {exc}"))
```

It also discovers optional placement methods with `getattr`:

```python
def pre_tool_use(self, context: PreToolUseContext) -> HookDecision:
    return self._decision_placement(
        "pre_tool_use",
        "on_pre_tool_use",
        context,
    )
```

How to read it:

1. A hook may implement only `on_event`.
2. A hook may also implement `on_pre_tool_use`.
3. If any PreToolUse hook returns `allowed=False`, the current tool call is blocked.
4. If a hook raises, the failure is recorded in `HookManager.failures` and does not crash the loop.

State change: placement hooks do not change messages unless PreToolUse explicitly blocks a tool; a block produces a model-visible failed observation.

Boundary: this is not a full approval UI or human-in-the-loop system. It only makes lifecycle positions real.

</details>

## 3.5 PreToolUse is not a permission engine

PreToolUse can `allow` or `block` the current tool call, but Chapter 3 deliberately stops short of a complete permission system.

When a hook blocks a tool:

```text
pre_tool_use.started
pre_tool_use.completed allowed=false
tool.failed blocked=true
role="tool" failed observation enters the next model turn
```

It does not:

```text
open an approval modal
wait for human confirmation
write durable policy
mutate the tool registry
```

This matters. Chapter 3 answers "where can lifecycle behavior be influenced?" Full permission/approval belongs later, when MCP, external tools, background work, and production risk make it meaningful.

## 3.6 Tool lifecycle exactly-once

Every tool call should be easy to teach and test:

```text
successful tool  -> one tool.started + one tool.completed
unknown tool     -> one tool.started + one tool.failed
tool exception   -> one tool.started + one tool.failed
pre-tool blocked -> zero tool.started + one tool.failed
policy stop      -> zero tool.started for pending calls
```

Code:

```text
src/klara/core/loop.py
src/klara/tools/executor.py
tests/klara/core/test_loop.py
```

Reader takeaway: `tool.started` means the tool actually began executing; a PreToolUse-blocked call should not pretend it started.

## 3.7 JSONL trace: developer view

JSONL trace stores the public event schema. It is not UI state and it is not provider hidden reasoning.

A trace event looks like:

```json
{
  "schema_version": 1,
  "event_id": "evt_...",
  "seq": 7,
  "type": "tool.completed",
  "run_id": "run_...",
  "timestamp": "2026-06-18T...",
  "payload": {
    "turn_index": 0,
    "tool_result": {
      "name": "current_time",
      "ok": true,
      "content_preview": "...",
      "content_length": 128
    }
  }
}
```

Notice `content_preview/content_length`: trace can record compact observations, but UI should not display full tool content as answer text.

Code:

```text
src/klara/core/hooks.py
apps/api/services/app_store.py
```

## 3.8 API/SSE projection: product view

The API does not send every core event raw to the frontend. `RunEventProjector` projects public lifecycle events into product-facing run events:

```text
llm.started        -> llm_call_started
llm.completed      -> llm_call_completed
tool.started       -> tool_call_started
tool.completed     -> tool_call_completed
tool.failed        -> tool_call_failed
pre_tool_use.*     -> hook_placement_*
tool_policy.stopped -> policy_stop
```

Code:

```text
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/api/services/sse_bus.py
apps/api/schemas.py
tests/apps/api/test_run_event_projector.py
```

`RunService` now keeps only a thin adapter: the core hook receives `KlaraEvent`, the projector returns one or more `ProjectedRunEvent` values, and the service persists and streams them over SSE.

Reader takeaway: trace and frontend come from the same public event stream, but the projection layer decides what is appropriate for users.

## 3.9 Frontend run surface: tools and status for users

The frontend in Chapter 3 is not a Thinking UI and not a RAG module timeline. It renders runtime public projection as a lightweight run surface:

```text
assistant label
-> KlaraRunStatus
-> KlaraRunSurface
   -> compact lifecycle timeline
   -> tool cards
   -> hook badges
   -> trace saved state
-> assistant answer markdown
```

Code:

```text
apps/web/src/components/ChatWorkspace.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
apps/web/src/types/domain.ts
apps/web/src/api/client.ts
```

`answer_delta` still only updates the assistant answer. `workstream_note` and tool cards do not enter assistant message content.

## 3.10 Optional narrator: translating real runtime events into one natural note

The narrator is the final capstone of this chapter, not the main feature. It is default-off, lives in the API/app projection layer, and does not belong to core.

It can only generate short notes from real `RunEventRecord` evidence:

```json
{
  "event_type": "workstream_note",
  "payload": {
    "text": "...",
    "source": "narrator_model",
    "phase": "thinking",
    "evidence_event_ids": ["evt_..."],
    "display": {"ephemeral": false}
  }
}
```

Code:

```text
apps/api/services/workstream_narrator.py
src/klara/prompts/workstream_narrator.md
tests/apps/api/test_workstream_narrator.py
```

Limits:

- it does not enter `MessageRecord.content`
- it does not enter later main-model messages
- it does not reveal raw chain-of-thought
- it cannot claim search, reading, running, verification, or edits unless recent events prove them
- narrator failure does not fail the main run

Reader takeaway: natural-language runtime notes are an experience enhancement over event projection, not hidden reasoning display.

## 3.11 What this chapter does not do

This chapter explicitly does not include:

- complete permission engine
- Todo Planning
- agent task ledger
- context compression
- memory write policy
- full harness/config refactor
- full provider streaming adapter
- OpenAI/Claude/DeepSeek reasoning stream integration
- raw chain-of-thought display

These capabilities need the hooks/trace event layer first, but they should not steal Chapter 3's main line.

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
3. Confirm the run surface shows tool cards and hook badges.
4. Open `/api/runs/{run_id}` and inspect events.
5. Delete the session and confirm related trace lines are purged.

## Small Experiments

1. Write a hook that implements only `on_event`, and confirm it receives every lifecycle event.
2. Write an `on_pre_tool_use` hook that returns `allowed=False`, and confirm the tool does not execute while the model sees a failed observation.
3. Make a hook raise, and confirm the run still completes while the failure is recorded in `HookManager.failures`.
4. Open the JSONL trace and replay one run by `seq`.
5. Observe that active runs are expanded by default and completed runs are collapsed by default.

## Next Chapter

Chapter 4 covers Harness And Config: now that loop, tools, hooks, and trace have boundaries, the next step is assembling provider, model, prompt, tools, hooks, and trace sink through one clear harness entry point.
