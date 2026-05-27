# Runtime Event Agent Notes

## Findings
- Existing frontend/backend `RunEvent` is a v0.1 DTO with `event_type` names like `answer_delta`.
- SSE replay/live architecture is strong.
- RunMargin currently hardcodes a single LLM Call step.

## Recommendation
- Add a public Klara event adapter instead of replacing backend DTOs.
- Map current backend events into future-proof, namespaced, public-only Klara events.
- Keep answer deltas separate from timeline rows and aggregate them.

## Risks
- Replacing the current DTO directly would break existing SSE handling.
- Without visibility/safe payload discipline, future tool/RAG events could leak private data.

## Acceptance Focus
- Public event has runId, seq, timestamp, kind, status, publicLabel, safePayload.
- Unknown future events should not crash UI.
- Mock minimal/calculator/rag/web/error/loop sequences exist for development.

## Challenges
- Backend may later need a canonical core event contract; this iteration uses frontend adapter.
