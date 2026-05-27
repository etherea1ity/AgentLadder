# Integration Lead Decision

## Final Decision
Implement P0/P1 Klara Presence with scoped React components + CSS/WAAPI-style transitions, using existing PNG assets as the true Klara body and adding an adapter from current backend Run events to public KlaraRunEvents.

## Technology Choice
- Primary now: React + TypeScript + scoped CSS.
- Rive: deferred until a `.riv` or vector source exists; no placeholder dependency.
- Lottie/WebM: deferred; better for canned hero loops, not stateful run events.
- GSAP Flip: not needed now; current anchor movement is simple enough for CSS transforms.
- Pure CSS alone is not enough for product semantics, so event mapping lives in TypeScript while CSS handles optical motion.

## Conflicts Resolved
- Conflict: Rive requested vs no Rive asset. Decision: no fake Rive; document fallback and keep CSS optical layer.
- Conflict: exact future RunEvent name vs existing DTO. Decision: keep existing DTO and add `KlaraRunEvent` adapter.
- Conflict: active Klara in message vs composer. Decision: running run owns active presence in the status row; composer uses active presence only when no current nonterminal run exists; completed messages use stamp.
- Conflict: Live Run should show chain vs not pre-seed future. Decision: panel renders only adapted events already present; mock scenarios are dev-only.

## Fallback
If assets are insufficient, keep PNG mark-only, avoid SVG, and document design-source export requirement.
