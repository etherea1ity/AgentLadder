# Chapter 3: Hooks and Trace

Language: [Chinese](./README.md) | English

Previous: [Chapter 2: Tool Calling](./docs/chapters/ch02-tool-calling.en.md)

Next: Chapter 4: Harness And Config

Roadmap: [Klara Roadmap](./docs/skills/roadmap.md)

Full chapter: [docs/chapters/ch03-hooks-and-trace.en.md](./docs/chapters/ch03-hooks-and-trace.en.md)

Algorithm overlay: [Evidence, distillation, MoE, and FP16/FP4 lab suite](./docs/labs/algorithm-suite.en.md)

Final cloud report: [Algorithm Suite Freeze](./docs/reports/algorithm/algorithm-suite-freeze.md)

---

## The Chapter In One Sentence

Klara does not hide a run inside a black box: the loop still owns only model and tool execution, but every lifecycle point emits an event, and hooks, JSONL trace, frontend Thinking, the right-side activity drawer, and Developer Debug all project from the same public event stream.

![Klara Chapter 3 Hooks and Trace](./docs/assets/ch03-hooks-and-trace.svg)

| What you see | What Klara does |
| --- | --- |
| `llm.started` | Records the model input boundary: message counts, role distribution, prompt hash, tool schemas |
| `llm.completed` | Records the model output boundary: content, tools, public thinking, provider reasoning |
| `tool.*` | Records real tool actions, duration, errors, and safe observation summaries |
| Thinking | Shows main-model public commentary or provider reasoning; no fake empty Thought |
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

Try a no-tool question:

```text
Hello
```

Then try a tool-shaped question:

```text
What time is it in Shanghai now?
```

Then try a current-information question:

```text
What is in the latest news today?
```

Watch for three things:

1. Thinking and the final answer are separate.
2. Tool calls and failures appear in Developer Debug.
3. `llm.started.input_profile` and `llm.completed.response_profile` help explain what each LLM turn saw and returned.

## What Changed

The Chapter 2 loop stays the same:

```text
model tool_calls -> runtime executes tools -> observations return to model
```

Chapter 3 adds observability:

```text
KlaraLoop
-> KlaraEvent
-> HookManager
-> JsonlTraceHook
-> RunEventProjector
-> Thinking / Activity / Developer Debug
```

This is not decorative UI. It is a stable event contract that lets us explain:

- which LLM turn called which tools
- which tool failed
- where token and latency cost went
- whether the model actually returned content
- whether Thinking came from public commentary, provider reasoning, or runtime transcript

## Key Source

```text
src/klara/core/loop.py
src/klara/core/hooks.py
src/klara/core/events.py
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
```

## Verify

```powershell
python -m pytest tests\klara\core\test_loop.py tests\apps\api\test_run_event_projector.py -q
python -m pytest
```

Current trace-profile verification:

```text
168 passed
```

Next chapter covers Harness And Config: how one Klara run is assembled before entering the loop, including model, provider, persona, tools, hooks, and trace sinks.
