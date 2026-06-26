# Chapter 3: Hooks and Trace

Language: [Chinese](./ch03-hooks-and-trace.md) | English

Previous: [Chapter 2: Tool Calling](./ch02-tool-calling.en.md)

Next: Chapter 4: Harness And Config

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## The Chapter In One Sentence

Klara does not hide a run inside a black-box function: the loop still owns only model and tool execution, but each lifecycle point emits an event, and hooks, JSONL trace, frontend Thinking, the right-side activity drawer, and Developer Debug all project from the same public event stream.

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

| What you see | What Klara does |
| --- | --- |
| `llm.started` | Records the model input boundary: message counts, role distribution, prompt hash, tool schemas |
| `llm.completed` | Records the model output boundary: content, tools, public thinking, provider reasoning |
| `tool.started/completed/failed` | Records real tool actions, duration, errors, and safe observation summaries |
| `assistant_activity_delta` | Shows public commentary written by the main model; it does not enter the final answer |
| Developer Debug | Shows engineering trace, tokens, duration, and payloads for teaching and debugging |

## Quick Experience

Start:

```powershell
.\scripts\dev.ps1
```

Open:

```text
http://127.0.0.1:5123
```

First ask a simple question:

```text
Hello
```

You should see one direct model answer. Developer Debug should show one LLM round and no tools.

Then ask a tool-shaped question:

```text
What time is it in Shanghai now?
```

You should see that the model can request a tool, trace shows `tool_call_started` and `tool_call_completed`, and the final answer contains only user-facing text.

Finally ask a current-information question:

```text
What is in the latest news today?
```

These questions are where Chapter 3 matters most. If the search provider returns a challenge page, a tool fails, the model retries several turns, or the final answer is incomplete, Developer Debug should show which layer failed.

## Real Problem: Final Text Is Not Enough

During debugging we saw several recurring cases:

- The model ran for a long time but ended with an empty or failed answer.
- Thinking showed repeated text that looked like reasoning but was repeated public commentary.
- Search returned challenge pages, and the model either gave up or over-trusted candidate snippets.
- A run contained several LLM and tool calls, but the frontend only showed the final text.

These problems should not be patched with another fixed prompt. Chapter 3 starts by making the runtime trajectory visible.

Chapter 3 does not change the Chapter 2 loop:

```text
model tool_calls -> runtime executes tools -> observations return to model
```

It adds observability around that loop:

```text
KlaraLoop
-> KlaraEvent
-> HookManager
-> JsonlTraceHook
-> RunEventProjector
-> Thinking / Activity / Developer Debug
```

## Mechanism 1: Hooks Attach To Lifecycle Points

Hooks have two jobs.

Observer hooks only watch events:

```text
on_event(event)
```

Placement hooks attach at fixed runtime positions:

```text
on_user_prompt_submit
on_pre_tool_use
on_post_tool_use
on_stop
```

`PreToolUse` can block one tool call, but it is not a full permission engine. This chapter teaches only the placement idea: if a hook blocks a tool, runtime produces a failed tool observation for the next model turn.

Source:

```text
src/klara/core/hooks.py
src/klara/core/loop.py
tests/klara/core/test_hooks.py
```

<details>
<summary>Expand: how HookManager isolates hook failures</summary>

A hook should not crash the whole run. `HookManager.emit()` calls hooks in order. If one hook raises, the failure is recorded:

```python
for hook in self._hooks:
    try:
        hook.on_event(event)
    except Exception as exc:
        self.failures.append((event.type, f"{type(exc).__name__}: {exc}"))
```

This protects the loop boundary:

- the loop emits events
- hooks observe or decide at placements
- a broken hook does not swallow the user's answer

Takeaway: hooks are lifecycle extensions, not a place to dump business rules.

</details>

## Mechanism 2: Trace Records Boundaries, Not Raw Prompts

The most important Chapter 3 trace change is the LLM input/output boundary.

Klara does not put full system prompts, full history, user text, or raw provider payloads into public trace. That would mix debugging, replay, and private material.

Instead, Klara records trace-safe profiles.

`llm.started` now includes:

```text
input_profile:
  message_count
  role_counts
  total_content_chars
  last_message_role
  last_message_chars
  tool_result_count
  assistant_tool_call_message_count
  system_prompt_chars
  system_prompt_hash
  tool_spec_count
  tool_names
  tool_spec_hash
  public_activity_update_count
  controller_count
  finalization
```

`llm.completed` now includes:

```text
response_profile:
  content_chars
  has_content
  external_tool_call_count
  internal_activity_call_count
  tool_call_names
  tool_call_ids
  has_activity_commentary
  activity_commentary_chars
  has_provider_reasoning
  provider_reasoning_chars
```

This answers concrete debugging questions:

- How much history did this model turn see?
- Was this a normal turn or a finalization turn?
- Were tool schemas visible?
- Did the model return final text, tool calls, public thinking, or provider reasoning?
- Did an empty answer come from the model, projection, or frontend rendering?

Source:

```text
src/klara/core/loop.py
apps/api/services/run_event_projector.py
tests/klara/core/test_loop.py
tests/apps/api/test_run_event_projector.py
```

<details>
<summary>Expand: how one LLM input boundary is produced</summary>

Before calling the model, the loop freezes the real request boundary:

```python
model_messages = tuple(messages)
system_prompt = self._system_prompt_for_turn(public_activity_updates)
model_tools = _model_visible_tool_specs(self.tool_executor.specs)
```

Then `llm.started` records a profile:

```python
"input_profile": _llm_input_profile(
    system_prompt=system_prompt,
    messages=model_messages,
    tools=model_tools,
    public_activity_updates=public_activity_updates,
    controller_count=len(self.controllers),
)
```

The trace does not include raw `system_prompt` or raw `messages`. It records sizes, counts, role distribution, tool names, and hashes.

The model call then reuses the exact same `system_prompt / model_messages / model_tools`:

```python
response = self.llm.complete(
    system_prompt=system_prompt,
    messages=model_messages,
    tools=model_tools,
    model=self.model,
    thinking_enabled=self.thinking_enabled,
)
```

Runtime state change:

```text
messages unchanged
tools unchanged
trace gains llm.started
the LLM receives the same boundary represented by the profile
```

</details>

<details>
<summary>Expand: how one LLM output boundary is produced</summary>

After the model returns, the loop separates executable tool calls from internal public activity:

```python
prepared_calls = _prepare_tool_calls(response.tool_calls)
```

`update_activity` is an internal public-thinking tool. It does not execute as a runtime tool. Other tool calls go to the executor.

`llm.completed` then receives the output profile:

```python
"response_profile": _llm_response_profile(
    response=response,
    prepared_calls=prepared_calls,
    activity_payload=activity_payload,
)
```

This profile does not store answer text. It records:

- content length
- whether content exists
- external tool count
- internal activity tool count
- tool names and ids
- whether public commentary exists
- whether provider reasoning exists

If the UI shows no answer, first check `has_content` and `content_chars`. If the model returned no content, it is a model/tool-turn issue. If the model did return content, the bug is in projection or frontend rendering.

</details>

## Mechanism 3: Thinking, Activity, And Debug Stay Separate

Klara has three user-visible chains.

### A. Provider reasoning

This comes from native provider/model fields such as:

```text
reasoning_content
reasoning
thinking
```

If it exists, Klara can display it. If it does not, Klara does not fake it. It does not enter the final answer or the next model-visible history turn.

### B. Main model public commentary

This is public process text written by the main model. It can come from:

- `content + tool_calls`, where `content` is activity, not final answer
- `activity_commentary / public_activity / commentary`
- the internal `update_activity` tool

This is one of the main Thinking sources, but it is not hidden chain-of-thought. It can say "I will check public sources first"; it cannot pretend the search has already happened.

### C. Runtime action transcript

This is what the runtime actually did:

```text
web_search
web_fetch
image_generate
current_time
tool failed
```

It is agent workstream, not model thinking. Public Activity shows only safe summaries; full arguments, URLs, and raw payloads stay in Developer Debug.

## Mechanism 4: Developer Debug Is Engineering Surface

Developer Debug is collapsed by default and lives below the answer. It may show:

- LLM rounds
- token metrics
- duration / latency
- tool argument previews
- observation previews
- raw payloads
- trace saved state

This surface is for developers and teaching. The user reading path should not be flooded with raw trace, tool cards, or payloads.

Source:

```text
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraActivityDrawer.tsx
```

## How To Read One Run

Read trace in this order:

```text
run_created
thinking_started
llm_call_started
llm_call_completed
assistant_activity_delta?
tool_call_started?
tool_call_completed / tool_call_failed?
llm_call_started ...
answer_streaming_started
answer_delta...
answer_completed
run_completed
```

If the answer is wrong or missing, ask four questions first:

1. Does `llm_call_started.input_profile.tool_names` include the needed tool?
2. What is `llm_call_completed.response_profile.external_tool_call_count`?
3. Did the terminal tool event complete or fail?
4. Did `answer_delta` actually start streaming?

That is the core Chapter 3 skill: turn "the model feels broken" into "which layer failed?"

## Tests

Targeted tests:

```powershell
python -m pytest tests\klara\core\test_loop.py tests\apps\api\test_run_event_projector.py -q
```

Full tests:

```powershell
python -m pytest
```

The trace profile change was verified with:

```text
168 passed
```

## Out Of Scope

Chapter 3 does not implement:

- raw chain-of-thought display
- intent routing
- domain guards
- keyword search rules
- source ranking
- grounding verification
- memory
- context compression
- LangGraph migration

Those belong to later chapters. Chapter 3 only locks the boundary between hooks, trace, Thinking, Activity, and Developer Debug.

## Next Chapter

Chapter 4 covers Harness And Config: how one Klara run is assembled before entering the loop, including model choice, provider, persona, visible tools, hooks, trace sinks, and frontend/backend run creation.
