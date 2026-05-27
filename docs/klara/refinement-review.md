# Klara Presence Refinement Review

Date: 2026-05-27

## Review agents

### UI / Motion Agent
- Finding: small Klara still risked reading as a badge/spinner because capability dots orbited around composer/status marks.
- Decision: suppress capability satellites outside the run panel; keep small Klara as mark + halo + one weak arc only.
- Fixes: rewrote `styles/klara.css`, changed `KlaraPresence` to show chips only in panel, made idle composer nearly still.

### UX / Interaction Agent
- Finding: Run panel exposed mock scenario controls, View run toggled closed unexpectedly, empty Send looked active, model picker was changeable mid-run, mobile sidebar could be unreachable.
- Decision: remove production mock controls, make View run open/switch only, close via X, disable empty send, lock model picker during active runs, add mobile sidebar access.
- Fixes: updated `KlaraRunPanel`, `KlaraRunStatus`, `ChatWorkspace`, `RunMargin`, `App`, and mobile CSS.

### Architecture Agent
- Finding: handoff orchestration was embedded in `ChatWorkspace`, CSS was override-heavy, handoff timers/selectors were brittle.
- Decision: extract handoff logic into a Klara component hook, add cleanup, double-RAF measurement, escaped attribute selectors, and consolidate Klara CSS.
- Fixes: added `components/klara/useKlaraHandoff.tsx`; `ChatWorkspace` now only consumes `handoff` state.

### QA / Verification Agent
- Finding: no Klara-specific tests for active vs static stamp; Run panel public activity and production mock controls needed verification.
- Decision: add Klara status tests and extend E2E checks.
- Fixes: added `KlaraRunStatus.test.tsx`; updated E2E to assert safe Run Margin behavior, no mock controls, and disabled empty send.

## Final acceptance after refinement

- Small Klara is no longer a badge/sphere; the bitmap stays stable.
- Idle composer Klara is almost still; focus/typing gently brightens and emits restrained particles.
- Active Klara handoff logic is isolated, cleaned up, and reduced-motion aware.
- Run panel now shows public activity only; mock run controls are removed from production UI.
- View run opens/switches; the right panel X closes.
- Empty send is disabled; model selection locks during active runs.
- Completed runs render as static stamps.
- Tests and build pass.


## Rive Runtime Refinement

- Replaced CSS halo/orbit/particle animation with `KlaraRiveField`, backed by `@rive-app/canvas-advanced`.
- Removed unused DOM particle and CSS capability-orbit components.
- Klara bitmap remains stable; Rive draws only the surrounding optical field.
- Vitest now runs with the threads pool to avoid fork startup timeouts after the WASM runtime dependency.
- Verification: `npm test`, `npm run build`, and backend `pytest` passed after the Rive conversion.
