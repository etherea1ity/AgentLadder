# Klara Chapter 3 Package: Hooks, Trace, Activity

This package documents the Chapter 3 boundary: Klara keeps public thinking activity, runtime trace, and developer debug separate.

## User-Facing Shape

Top Thinking Trigger:

```text
active:     mini Klara + Thinking... + timer
completed:  mini Klara + Thought for X >
```

The trigger is intentionally small. It does not show tool chains, raw payloads, hidden reasoning, or developer trace.

Activity Drawer:

- `Klara thinking`: narrator-generated public activity items after completion.
- `Agent activity`: runtime activity items projected from real events during the run.
- Every item cites `evidence_event_ids`.
- No fake periodic notes are generated.
- If the narrator is unavailable, the run completes with `has_summary=false`.

Developer Debug:

- LLM rounds with token and duration fields when present.
- Tool cards with status, duration, argument preview, observation preview.
- Trace events with event id and timestamp.
- Raw payloads only inside the developer panel.

## Why This Is The Chapter 3 Contract

Klara follows the agent product pattern we want to teach:

```text
GPT-like Thought entry
+ Claude Code / Codex-like observable activity
+ developer-only trace/debug
```

The important separation is:

```text
public activity summary != raw chain-of-thought
developer debug          != user thinking UI
runtime events           != answer content
```

The narrator model is not the answer model. It reads only public runtime events, writes strict JSON activity items, and never enters the conversation history.

## Files To Read

```text
docs/chapters/ch03-hooks-and-trace.md
docs/chapters/ch03-hooks-and-trace.en.md
apps/api/schemas.py
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/api/services/workstream_narrator.py
src/klara/prompts/thinking_summary_narrator.md
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraActivityDrawer.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
```

## Verification

```powershell
python -m pytest
cd apps\web
npm test
npm run build
```

Do not commit generated folders or secrets:

```text
node_modules
dist
data
.env
cache files
```
