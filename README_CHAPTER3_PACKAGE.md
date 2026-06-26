# Klara Chapter 3 Package: Hooks, Trace, Thinking

This package documents the Chapter 3 boundary: hooks observe the loop, trace records the evidence, Thinking stays user-facing, and Developer Debug stays engineering-facing.

## User-Facing Shape

Thinking lives inside the assistant message, before the final answer.

```text
active:    Klara + latest public commentary when the model produced one
complete:  Thought for X > when there is visible Thinking content
```

The visible Thinking content can come from:

- provider reasoning summaries, when the selected model exposes one;
- main-model public commentary, such as assistant text emitted alongside tool calls;
- compact runtime action transcript entries in the Activity drawer.

If none of those exists, Klara does not show an empty Thought trigger. Duration still belongs in Developer Debug.

## Activity Drawer

The drawer is a user-facing explanation surface, not raw debug.

- Klara activity: public commentary produced by the main model.
- Agent activity: safe summaries of real runtime actions, such as tool name, status, result count, title, or domain.
- Provider reasoning: provider-visible reasoning summary when the model exposes one.

The drawer must not show full URLs, full queries, raw tool arguments, raw observations, raw payloads, secrets, or hidden chain-of-thought.

## Developer Debug

Developer Debug stays under the assistant answer and is collapsed by default.

It is allowed to show engineering details:

- LLM rounds and model names;
- input and response profiles;
- token and duration fields when available;
- tool arguments and observation previews;
- raw trace payloads in expandable debug sections.

The new trace profiles are intentionally boundary-shaped: they explain how many messages, tool specs, tool results, public activity updates, and response fields crossed the runtime boundary without storing raw prompts.

## Files To Read

```text
docs/chapters/ch03-hooks-and-trace.md
docs/chapters/ch03-hooks-and-trace.en.md
apps/api/schemas.py
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
src/klara/core/loop.py
src/klara/core/hooks.py
src/klara/core/messages.py
src/klara/infra/llm/openai_compatible.py
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
```

Do not commit generated folders or secrets:

```text
node_modules
dist
data
.env
cache files
```
