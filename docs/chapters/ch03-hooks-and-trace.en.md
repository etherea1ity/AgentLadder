# Chapter 3: Hooks and Trace

Language: [Chinese](./ch03-hooks-and-trace.md) | English

Previous: [Chapter 2: Tool Calling](./ch02-tool-calling.en.md)

Next: Chapter 4: Harness And Config

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## The Chapter In One Sentence

Klara does not hide the loop inside one opaque function; it emits public lifecycle events, lets hooks observe or lightly influence selected placements, and projects the same event stream into JSONL trace, API/SSE events, the frontend thinking block, and the developer trace panel.

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

| What you see | What Klara does |
| --- | --- |
| `user_prompt_submit.*` | Marks the boundary where a user request enters runtime |
| `llm.started/completed` | Records model calls with duration and usage metadata |
| `pre_tool_use.*` | Runs a hook placement before execution; it can allow or block one call |
| `tool.started/completed/failed` | Gives every tool call one real start and one terminal event |
| `post_tool_use.*` | Lets hooks observe the model-visible tool observation |
| `stop.*` | Marks the loop stop boundary before `run.completed` |
| JSONL trace | Stores replayable public events plus metrics |
| API/SSE projection | Shapes core events into product-facing run events |
| Thinking block | Shows `Thinking...`, then `Thought for Xs`, with an optional trace-grounded summary |
| Web evidence guard | Treats search as candidates, fetch as evidence, and fixtures as not results |

## Quick Experience

Start the app:

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

You should see a compact thinking block under the assistant label. While the run is active it says `Thinking...` with a timer and an event-grounded stream. When the run completes it says `Thought for Xs`; only the right-side chevron expands the details.

Then inspect the developer view:

```text
http://127.0.0.1:8011/api/runs/{run_id}
```

The API events and JSONL trace come from the same public lifecycle stream. Deleting a session also purges the related run events and trace lines.

## 3.1 Why Chapter 2's Tool Loop Was Not Enough

Chapter 2 made this real:

```text
model requests tool_calls
-> runtime executes tools
-> observations return to the next model turn
-> model writes a final answer
```

That is enough for tool calling, but not enough for observability. A user can ask why a search stopped, which tool failed, whether a hook blocked something, or whether the answer used fetched evidence rather than search snippets. Plain logging would make the loop noisy and brittle.

Chapter 3 adds a lifecycle layer:

```text
KlaraLoop
-> public KlaraEvent
-> HookManager
-> JsonlTraceHook
-> RunEventProjector
-> SSE / frontend thinking block / developer trace
```

Reader takeaway: the loop remains the runtime center, but lifecycle facts now have a stable public shape.

## 3.2 KlaraEvent: Public Lifecycle Events

`KlaraEvent` is the core contract for this chapter. It gives each public event a schema version, `event_id`, run-local `seq`, type, run id, timestamp, public payload, and an optional private payload reference.

Code:

```text
src/klara/core/events.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

Important boundary:

```text
public_payload      -> trace, API, and UI may project this
private_payload_ref -> a future pointer to private material, not private material itself
```

`EventSequencer` starts at `1` for each run and increments monotonically. That makes trace replay and teaching simple: read the JSONL lines for one `run_id`, sort by `seq`, and you have the public lifecycle.

Tool payloads use compact public shapes. A tool result may expose `name`, `ok`, `error`, `content_preview`, and `content_length`, but the frontend should not render long raw tool content as answer text.

## 3.3 Trace Has Events And Metrics

Chapter 3 trace is not just "what happened"; it also records how long it took and what token usage the provider reported.

Event-level metrics:

```json
{
  "type": "llm.completed",
  "payload": {
    "turn_index": 0,
    "tool_call_count": 1,
    "usage": {
      "prompt_tokens": 128,
      "completion_tokens": 64,
      "total_tokens": 192
    },
    "metrics": {
      "duration_ms": 924,
      "prompt_tokens": 128,
      "completion_tokens": 64,
      "total_tokens": 192,
      "token_source": "reported"
    }
  }
}
```

Tool terminal events also include `metrics.duration_ms`. Blocked tools use a zero duration because no execution started. Run completion includes run-level latency and usage totals.

`token_source` can be:

```text
reported  -> the provider returned usage
estimated -> reserved for a future estimator
unknown   -> no reliable usage was available
```

Reader takeaway: event trace says what happened; metrics trace says how costly or slow it was.

## 3.4 Observer Hooks Do Not Own Correctness

An observer hook receives events and should not decide whether the loop succeeds. `JsonlTraceHook` is the simplest example:

```text
KlaraLoop._emit(event)
-> HookManager.emit(event)
-> JsonlTraceHook.on_event(event)
-> event.to_public_dict() is appended to JSONL
```

Code:

```text
src/klara/core/hooks.py
apps/api/services/app_store.py
tests/apps/api/test_app_store_delete.py
```

The JSONL shape uses top-level `run_id`. App-store lookup and purge therefore use `record.get("run_id") == run_id`. That keeps session deletion aligned with trace deletion.

Hook failure isolation matters: if an observer hook raises, `HookManager.failures` records it and the loop continues.

## 3.5 Lifecycle Placements: Submit, PreToolUse, PostToolUse, Stop

Hooks can also opt into lifecycle placements:

```text
UserPromptSubmit -> when the user request enters runtime
PreToolUse       -> before one tool call executes
PostToolUse      -> after a tool observation exists
Stop             -> before the run completes
```

Code:

```text
src/klara/core/hooks.py
src/klara/core/loop.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

The decision object is intentionally small:

```python
@dataclass(frozen=True)
class HookDecision:
    allowed: bool = True
    reason: str = ""
    public_metadata: dict[str, object] = field(default_factory=dict)
```

`HookManager` discovers optional methods with `getattr`, so a hook can implement only `on_event` or also implement `on_pre_tool_use`, `on_post_tool_use`, and friends.

If a PreToolUse hook returns `allowed=False`, the current tool is blocked. The tool is not executed, no `tool.started` event is emitted, and the model receives a failed tool observation:

```text
pre_tool_use.started
pre_tool_use.completed allowed=false
tool.failed blocked=true
role="tool" observation: "Tool blocked by hook: ..."
```

This is not a permission engine. It does not show approval UI, wait for a person, mutate durable policy, or rewrite the tool registry.

## 3.6 Tool Lifecycle Exactly Once

Tool events are deliberately pairable:

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

`tool.started` means execution really began. If a hook blocks a tool, the terminal failure is still visible, but the start event does not pretend the tool ran.

## 3.7 API/SSE Projection

The API does not stream raw core events directly. `RunEventProjector` turns public lifecycle events into product-facing run events:

```text
llm.started          -> llm_call_started
llm.completed        -> llm_call_completed
tool.started         -> tool_call_started
tool.completed       -> tool_call_completed
tool.failed          -> tool_call_failed
pre/post hook events -> hook_placement_started/completed
tool_policy.stopped  -> policy_stop
```

Code:

```text
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/api/services/sse_bus.py
apps/api/schemas.py
tests/apps/api/test_run_event_projector.py
```

The projector also owns product-facing usage accumulation. `answer_delta` remains answer streaming; it is not trace. `thinking_summary_delta` remains visible thinking summary content; it is not assistant message content and is not sent back into model-visible history.

## 3.8 GPT-Style Thinking Block

The main user-facing surface is now a GPT-style thinking block:

```text
active run:
  Thinking... 4.2s
  small event-grounded stream when expanded

completed run:
  Thought for 23.9s
  right-side chevron expands details
```

Code:

```text
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
apps/web/src/components/ChatWorkspace.tsx
apps/web/src/types/domain.ts
apps/web/src/api/client.ts
```

The block is not raw chain-of-thought. During the run it derives a small visible stream from public events such as model started, tool started, tool completed, hook completed, and run completed. After the run, an optional narrator can generate one short summary from the completed public trace.

If narrator is unavailable, Klara still emits:

```text
thinking_summary_started
thinking_summary_completed has_summary=false
```

The UI then shows `Thought for Xs` without inventing a fake summary.

The developer trace panel stays separate and visually weaker:

```text
Developer trace · 38 events · 3 tools
```

Tool cards and hook badges belong there, not inside the main thinking summary.

## 3.9 Thinking Summary Narrator

The thinking summary narrator is a capstone, not the core mechanism. It runs after the main loop completes and before answer streaming starts. Its input is the completed public run event list, not private scratchpad text.

Prompt:

```text
src/klara/prompts/thinking_summary_narrator.md
```

Service:

```text
apps/api/services/workstream_narrator.py
tests/apps/api/test_thinking_summary.py
```

Rules:

- summarize what the runtime actually did
- use evidence event ids
- match the user's language
- do not answer the user's question
- do not expose raw tool arguments, secrets, full URLs, file contents, hidden reasoning, or chain-of-thought
- reject unsupported action claims
- ignore invalid JSON, empty text, or forbidden reasoning language

`workstream_note` remains as a legacy-compatible event type, but the default Chapter 3 user surface is the completed-run thinking summary.

## 3.10 Web Evidence Boundaries

The web tools in Chapter 3 teach an important trace lesson: search results are candidates, not facts.

Code:

```text
src/klara/tools/builtin/web_search/tool.py
src/klara/tools/builtin/web_fetch/tool.py
src/klara/services/web/source_quality.py
src/klara/services/web/search.py
src/klara/context/web_evidence.py
tests/klara/services/test_web_search.py
tests/klara/tools/test_web_tools.py
tests/klara/context/test_web_evidence.py
```

For current sports queries, Klara now annotates search results:

```text
official      -> fifa.com
wire          -> reuters.com, apnews.com
sports_media  -> ESPN, Guardian football, BBC Sport, Fox Sports
aggregator    -> SEO or score-aggregation style sites
unknown       -> everything else
```

This is not an allowlist and it does not forbid other sources. It is a quality signal for evidence selection and trace teaching.

The guard reminds the model:

- search snippets are not enough for concrete facts
- fetch at least relevant sources for current sports unless one official page directly contains the needed fact
- aggregator-only evidence cannot support concrete scores
- fixtures are not results
- a scheduled match with no verified score is not `0:0`
- separate completed results, scheduled or in-progress fixtures, and source limitations

For the teaching prompt:

```text
帮我搜一下世界杯最新进展
```

Expected behavior in the June 18 scenario:

- call `web_search`
- fetch the FIFA schedule and at least one news, wire, or sports-media source when latest results are needed
- distinguish completed June 17 results from June 18 scheduled or in-progress fixtures
- include source URLs in the answer
- show `web_search` and `web_fetch` tool events with latency in trace
- let the thinking summary describe evidence selection at a high level, without claiming unsupported work

## 3.11 What This Chapter Does Not Do

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

Todo belongs to Chapter 5. RAG/module pipelines belong to later chapters. The thinking summary is only a public-trace projection, not hidden reasoning.

## Code Index

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
src/klara/core/tools.py
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
apps/web/src/components/ChatWorkspace.tsx
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

Manual checks:

1. Start `.\scripts\dev.ps1`.
2. Ask a `current_time` question and confirm the thinking block timer, chevron behavior, tool card, and trace panel.
3. Ask `帮我搜一下世界杯最新进展` and confirm the answer separates fetched evidence, completed results, fixtures, and source limitations.
4. Open `/api/runs/{run_id}` and inspect events plus metrics.
5. Delete the session and confirm related trace data is purged.

## Small Experiments

1. Write a hook that implements only `on_event` and confirm it receives lifecycle events.
2. Write an `on_pre_tool_use` hook that returns `allowed=False` and confirm the tool does not execute.
3. Make a hook raise and confirm the run still completes while the failure is recorded.
4. Open JSONL trace and replay one run by `seq`.
5. Compare search-only evidence with fetched evidence on a current sports query.

## Next Chapter

Chapter 4 covers Harness And Config: once loop, tools, hooks, trace, metrics, and projections have clear boundaries, the next step is assembling provider, model, prompt, tools, hooks, policies, and trace sinks through one harness entry point.
