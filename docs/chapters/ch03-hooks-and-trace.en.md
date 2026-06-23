# Chapter 3: Hooks and Trace

Language: [Chinese](./ch03-hooks-and-trace.md) | English

Previous: [Chapter 2: Tool Calling](./ch02-tool-calling.en.md)

Next: Chapter 4: Harness And Config

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## The Chapter In One Sentence

Chapter 3 does not add business rules to the loop. It separates Klara's runtime into three surfaces: a GPT-like Thinking Trigger, an Activity Drawer, and Developer Debug.

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

## The Three Surfaces

### 1. Top Thinking Trigger

The main user path stays lightweight:

```text
active:    Klara · Thinking... 1.2s
complete:  Klara · Thought for 24.2s >
```

A completed `Thought for X` is content-backed. It appears only when Klara has at least one visible item from:

- provider/model reasoning summary; or
- narrator-generated Klara activity items.

If neither exists, Klara does not show an empty `Thought for X`. Runtime duration still appears in Developer Debug.

Interaction is explicit: the left side is mini Klara icon + label, and the right chevron is the only drawer trigger. Clicking the label does not open the drawer.

### 2. Activity Drawer

The drawer has two public sections:

```text
Model thinking  -> provider_reasoning summary; hidden when absent
Klara activity  -> narrator_model workstream items generated from facts
```

"Real thinking" here does not mean raw chain-of-thought:

- `Model thinking` comes from a provider/model-visible reasoning summary. Klara shows it only when the provider returns it.
- `Klara activity` comes from `activity_fact_recorded` plus a narrator model. Runtime records facts; the narrator writes public activity prose.
- If the narrator is unavailable, returns invalid JSON, or fails validation, Klara does not invent template prose. The failure is visible only in Developer Debug.

### 3. Developer Debug

Developer Debug is collapsed by default and is for engineering/teaching:

- LLM rounds: turn, model, duration, input/output/total tokens, token source.
- Tools: tool name, status, duration, arguments preview, observation preview.
- Activity facts: structured facts, request preview, evidence ids.
- Narrator diagnostics: started, completed, rejected, failed.
- Trace: event id, created_at, event_type, raw payload.

## The Two Real Sources

### A. Model Thinking / Provider Reasoning

If a provider returns public fields such as `reasoning_content`, `reasoning`, or `thinking`, Klara projects them into:

```text
provider_reasoning_delta
provider_reasoning_completed
```

This metadata is UI-only. It is not written into assistant message content and does not enter the next main-model history turn.

### B. Klara Activity / Agent Workstream

Runtime emits facts, not visible sentences:

```json
{
  "id": "fact_evt_...",
  "kind": "request_orientation",
  "status": "completed",
  "source_event_type": "thinking_summary_started",
  "evidence_event_ids": ["evt_..."],
  "request": {
    "preview": "redacted short user-request preview",
    "language": "en"
  }
}
```

Tools, search results, fetched pages, image generation, and errors produce their own facts. Facts must not contain `title` / `body`, full URLs, raw arguments, raw observations, secrets, or hidden reasoning.

The narrator turns facts into public activity items:

```json
{
  "title": "Request understood",
  "body": "Klara identified the request goal and prepared a concise response.",
  "kind": "orientation",
  "source": "narrator_model",
  "evidence_fact_ids": ["fact_evt_..."],
  "evidence_event_ids": ["evt_..."],
  "confidence": 0.8
}
```

If an item claims Klara searched, opened, read, verified, generated, edited, or tested something, corresponding facts must support it.

## Why The Previous Version Felt Fake

The earlier version had several wrong signals:

- `Thought for X` appeared even when only a timer existed.
- `provider_reasoning_delta` existed as a type but no backend emitted it.
- The drawer could open into an empty public state.
- Runtime events were directly templated into phrases like "Reading request" or "Writing answer".

The corrected rule is simple: if there is no provider reasoning and no safe narrator item, do not show `Thought for X`.

## Quick Experience

Start:

```powershell
.\scripts\dev.ps1
```

Open:

```text
http://127.0.0.1:5123
```

Try:

```text
What time is it in Shanghai now?
Search for the latest World Cup schedule.
Generate an image of Klara.
```

Check:

1. The top row does not show an empty `Thought for X`.
2. Activity Drawer only shows `Model thinking` or `Klara activity`, never raw trace.
3. Developer Debug is the only place for tools, facts, narrator diagnostics, raw payloads, and metrics.

## Out Of Scope

Chapter 3 does not add raw chain-of-thought display, intent routing, domain guards, keyword search rules, source ranking, grounding verification, memory, or context compression.

Those belong to later chapters. This chapter locks the boundary between thinking, activity, and debug.
