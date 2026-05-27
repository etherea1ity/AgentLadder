# Klara Presence System

Klara Presence separates brand identity from runtime activity.

## Product Model

- **Static Klara Stamp**: identity mark for completed or historical assistant messages. It is not animated and does not imply hidden thinking.
- **Active Klara**: the single live presence for the current non-terminal run or, when idle, the composer dock above the input.
- **Live Run Panel**: public activity trace for the selected run. It renders only events that happened or the current state inferred from the current run; it does not render chain-of-thought or future planned steps.

## Implementation

The current version uses React/TypeScript and scoped CSS rather than Rive. Klara's body is always the source PNG mark under `public/brand/klara/`; CSS only renders external halo, ring, dust particles, and capability satellites around the mark.

### Why no frontend redraw

The Klara mark is a designed brand asset. Recreating it with CSS/SVG paths would risk an inaccurate “fake” logo. The UI therefore uses the original PNG for the mark and applies optical motion outside it.

### Technology split

- **React/TypeScript**: maps backend run state and SSE events into public Klara events.
- **CSS/WAAPI-style transforms**: halo, orbit glint, focus/typing particles, status phase styling.
- **Rive**: deferred until the team has a `.riv` or clean vector source; it should own halo/orbit/dust state machines, not the main logo.
- **Lottie/WebM**: deferred for possible canned hero loops; not a good primary fit for event-driven runtime state.
- **GSAP Flip**: deferred; current composer/status anchoring does not require a heavy animation dependency.

## Event Discipline

The frontend keeps the existing v0.1 backend `RunEvent` DTO, then adapts it to `KlaraRunEvent`:

- `run_created` → `run.started`
- `thinking_started` → `ask.created`
- `llm_call_started` → `model.call.started`
- `answer_streaming_started` / first delta → `answer.started`
- `llm_call_completed` → `model.call.completed`
- `run_completed` → `run.completed`
- `run_failed` / `run_cancelled` → `run.error`

`answer_delta` updates answer text and is not displayed as one timeline row per chunk.

## Course Growth

- **v0.1 Minimal Agent**: core sun, model chip, trace chip; labels: Calling model, Writing answer, Completed.
- **v0.2 RAG**: source/retrieval satellites appear only when retrieval events exist.
- **v0.3 Agentic RAG**: loop grouping via `iteration` and verification chip.
- **v0.4 Memory**: memory chip/trail reserved through the event model.
- **v0.5 Research**: web + verification chips can coexist, capped at two visible satellites.
- **v0.6 MCP**: tool/permission/audit events can map to tool/trace chips.

## Accessibility

`prefers-reduced-motion: reduce` disables rotation, satellite orbit, and particles while preserving static halo and status text. View run remains a normal button with `aria-expanded` and `aria-controls`.
