# Klara Chapter 3 Package: Hooks, Trace, Activity

This package documents the Chapter 3 boundary: user-facing Thinking, fact-bound Activity, and Developer Debug are separate surfaces.

## User-Facing Shape

Thinking lives inside the assistant message, before the final answer:

```text
active:    Klara · Thinking... + timer
           one compact live preamble when available
complete:  Klara · Thought for X >
```

Completed `Thought for X` is content-backed. It appears only when at least one of these exists:

- a safe provider/model reasoning summary;
- a safe `thinking_preamble_delta`;
- safe narrator activity items.

If none exist, the trigger is not shown. The label itself does not open the drawer; only the right chevron does.

## Activity Drawer

- `Klara preamble`: the public live preamble, when available.
- `Model thinking`: safe `provider_reasoning` summaries only; hidden when unavailable.
- `Klara activity`: `narrator_model` items generated from structured `activity_fact_recorded` events.
- No runtime/fallback template prose is shown.
- If the narrator fails or is unavailable, diagnostics go to Developer Debug instead of public activity.

## Developer Debug

- LLM rounds with token and duration fields when present.
- Tool cards with status, duration, argument preview, observation preview.
- Activity facts with request preview and evidence ids.
- Narrator diagnostics: started, completed, rejected, failed.
- Trace events and raw payloads only inside the developer panel.

## Why This Is The Chapter 3 Contract

Klara follows the product pattern we want to teach:

```text
GPT-like live preamble + Thought entry
+ safe provider reasoning when available
+ evidence-bound narrator activity
+ developer-only trace/debug
```

The important separation is:

```text
provider reasoning summary != raw chain-of-thought
live preamble              != final answer
narrator activity          != runtime template prose
developer debug            != user thinking UI
runtime facts              != answer content
```

The narrator model is not the answer model. It reads only structured public facts or a redacted request preview, writes strict JSON, and never enters the conversation history.

## Files To Read

```text
docs/chapters/ch03-hooks-and-trace.md
docs/chapters/ch03-hooks-and-trace.en.md
apps/api/schemas.py
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/api/services/workstream_narrator.py
src/klara/core/messages.py
src/klara/infra/llm/openai_compatible.py
src/klara/prompts/thinking_preamble_narrator.md
src/klara/prompts/thinking_activity_narrator.md
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraActivityDrawer.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/activityItems.ts
```

## Verification

```powershell
python -m pytest
cd apps\web
npm test
npm run build
npm audit --omit=dev
```

Do not commit generated folders or secrets:

```text
node_modules
dist
data
.env
cache files
```
