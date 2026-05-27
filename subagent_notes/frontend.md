# Frontend Agent Notes

## Findings
- Klara UI is currently scattered across ChatWorkspace/Sidebar/global CSS.
- App owns runtime state; ChatWorkspace is presentation, RunMargin is selected-run display.
- Markdown/KaTeX rendering is sensitive and should not be wrapped or rewritten casually.

## Recommendation
- Create `components/klara/` boundary for presence components.
- Keep runtime ownership in App and adapt existing `Run`/events into Klara public events.
- Do not touch `AssistantContent` markdown pipeline.

## Risks
- Global CSS has many overrides; new selectors must be scoped.
- Existing tests depend on Run Margin/open trace semantics.

## Acceptance Focus
- Existing send/stream/stop/delete/markdown tests remain green.
- Presence covers queued/thinking/streaming/completed/failed/cancelled.

## Challenges
- Runtime needs richer event mapping later, but current backend is v0.1 LLM-only.
