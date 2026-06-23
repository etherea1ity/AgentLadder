# Klara Chapter 3 Package: Hooks, Trace, Activity

This package documents the Chapter 3 boundary: public thinking/activity, runtime facts, and developer debug are separate surfaces.

## User-Facing Shape

Top Thinking Trigger:

```text
active:    Klara · Thinking... + timer
complete:  Klara · Thought for X >
```

Completed `Thought for X` is content-backed. If there is no provider reasoning and no safe narrator activity item, the trigger is not shown. The label itself does not open the drawer; only the right chevron does.

Activity Drawer:

- `Model thinking`: safe `provider_reasoning` summaries only; hidden when unavailable.
- `Klara activity`: `narrator_model` items generated from structured `activity_fact_recorded` events.
- No runtime/fallback template prose is shown.
- If the narrator fails or is unavailable, diagnostics go to Developer Debug instead of public activity.

Developer Debug:

- LLM rounds with token and duration fields when present.
- Tool cards with status, duration, argument preview, observation preview.
- Activity facts with request preview and evidence ids.
- Narrator diagnostics: started, completed, rejected, failed.
- Trace events and raw payloads only inside the developer panel.

## Why This Is The Chapter 3 Contract

Klara follows the product pattern we want to teach:

```text
GPT-like Thought entry
+ safe provider reasoning when available
+ evidence-bound narrator activity
+ developer-only trace/debug
```

The important separation is:

```text
provider reasoning summary != raw chain-of-thought
narrator activity          != runtime template prose
developer debug            != user thinking UI
runtime facts              != answer content
```

The narrator model is not the answer model. It reads only structured public facts, writes strict JSON activity items, and never enters the conversation history.

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
