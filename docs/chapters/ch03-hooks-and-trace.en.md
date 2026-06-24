# Chapter 3: Hooks and Trace

Language: [Chinese](./ch03-hooks-and-trace.md) | English

Previous: [Chapter 2: Tool Calling](./ch02-tool-calling.en.md)

Next: Chapter 4: Harness And Config

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## The Chapter In One Sentence

Chapter 3 does not add business rules to the loop. It separates one Klara assistant turn into three surfaces: lightweight Thinking before the answer, an Activity Drawer on the right, and developer-only Debug below the answer.

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

## Where Thinking Lives

Thinking belongs inside the assistant message, before the final answer body.

It is not global loading, not the bottom debug panel, and not a large trace frame. During a run, it should feel like this:

```text
Klara · Thinking... 3.2s
I first understood that you are asking for the latest World Cup status, so this needs current sources rather than model memory alone.

The final answer starts appearing progressively...
```

After completion, it collapses to:

```text
Klara · Thought for 24.2s >
Final answer body
Developer debug · collapsed
```

`Thought for X` must be backed by real visible content. If provider reasoning, main-model public commentary, and runtime action transcript are all absent, Klara does not show an empty `Thought for X`; duration remains available in Developer Debug.

## The Three Public Chains

### A. Provider Reasoning

This is the public reasoning summary returned natively by a provider or model, such as `reasoning_content`, `reasoning`, or `thinking`.

Klara projects it into:

```text
provider_reasoning_delta
provider_reasoning_completed
```

This metadata is UI-only. It is not written into the final assistant answer and does not enter the next main-model history turn. If the provider does not return reasoning, Klara does not invent it.

### B. Main Model Public Commentary

This is public text written by the main model for the user. It is not hidden chain-of-thought.

The first version supports two sources:

- structured fields from a provider or wrapper: `activity_commentary`, `public_activity`, `commentary`
- `content + tool_calls` in the same model response, where `content` becomes public activity commentary instead of the final answer

Its meaning is:

```text
I understood what the user is asking.
I will handle it this way next.
Klara will continue with this action.
```

It is projected into:

```text
assistant_activity_delta
assistant_activity_completed
```

This commentary does not enter the final answer, does not enter the next main-model history turn, and is never mixed into answer chunks.

### C. Runtime Action Transcript

This is a compact summary of actions that really happened in the Klara runtime. It is not Thinking itself, but it belongs in the Activity Drawer as Agent activity.

Examples:

```text
web_search · 8 results · fifa.com · reuters.com
web_fetch · FIFA official schedule · fifa.com · 2300 chars
image_generate · 1 asset
current_time · completed
```

The public transcript shows only safe summaries: tool name, status, counts, source title, domain, and short preview. Full URLs, full queries, full arguments, full observations, and raw payloads stay in Developer Debug.

## The Three Surfaces

### 1. Thinking Trigger

The main path stays lightweight:

```text
active:    Klara · Thinking... 1.2s
complete:  Klara · Thought for 24.2s >
```

During an active run, if the main model produced public commentary, Klara shows the latest short line before the answer. After completion, Klara only shows the `Thought for X` trigger; the main chat never displays tool lists, event lists, or debug trace as Thinking.

Interaction is explicit: the left side is mini Klara icon + label, and the right chevron is the only drawer trigger. Clicking the text does not open the drawer.

### 2. Activity Drawer

The drawer is detail, not the main live experience. It has three sections:

```text
Model thinking  -> provider_reasoning_delta
Klara activity  -> assistant_activity_delta
Agent activity  -> runtime action transcript
```

If provider reasoning is absent, `Model thinking` is hidden. If main-model commentary is absent, `Klara activity` shows a lightweight empty state. If no runtime action happened, `Agent activity` is hidden.

The drawer never shows raw chain-of-thought, raw tool arguments, full URLs, raw observations, or raw payloads.

### 3. Developer Debug

Developer Debug is collapsed by default and is for engineering and teaching:

- LLM rounds: turn, model, duration, input/output/total tokens, token source
- Tools: tool name, status, duration, arguments preview, observation preview
- Activity facts: structured facts, evidence ids, safe metrics
- Trace: event id, created_at, event_type, raw payload

Developer Debug may show raw payloads because it is a developer surface. Thinking Trigger and Activity Drawer never show raw traces, tool cards, or event lists.

## Why This No Longer Fakes Thinking

The previous version had several wrong signals:

- `Thought for X` appeared even when only a timer existed.
- The Activity Drawer could open into an empty public state.
- Runtime events were wrapped into fixed prose such as "Reading request" or "Writing answer".
- Provider reasoning had event types but did not always have real content.
- The final answer appeared all at once.

The corrected rule is:

- Completed turns show `Thought for X` only when A, B, or C has visible content.
- Main-model public commentary is one primary Thinking source.
- Runtime action transcript stays compact and factual; it does not pretend to be model reasoning.
- The final answer can be chunked, but Thinking and Activity never mix into answer text.

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

1. The assistant message shows `Thinking...` first.
2. If the model produced public commentary, it appears before the answer.
3. A completed turn does not show an empty `Thought for X` when A/B/C content is absent.
4. Developer Debug is the only place for tools, raw payloads, and full trace.

## Out Of Scope

Chapter 3 does not add raw chain-of-thought display, intent routing, domain guards, keyword search rules, source ranking, grounding verification, memory, or context compression.

Those belong to later chapters. This chapter locks the boundary between Thinking, Activity, and Debug.
