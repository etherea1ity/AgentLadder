# Klara Rive Presence Runtime

## Decision

Klara's optical motion layer now uses the Rive Canvas Advanced runtime (`@rive-app/canvas-advanced`) instead of CSS keyframe animation.

The rendered layers are:

1. Stable Klara bitmap mark / lockup from `apps/web/public/brand/klara/`.
2. Rive-runtime canvas halo.
3. Rive-runtime incomplete orbit arcs.
4. Rive-runtime low-density particles.
5. Rive-runtime capability satellites in the run projection.

CSS is limited to sizing, placement, hit states, panel layout, and reduced-motion visibility. The Klara logo body is not redrawn and does not rotate.

## Why canvas-advanced instead of CSS

- The user requested the motion not be CSS-driven.
- The current design needs procedural halo/orbit/particle intensity tied to `KlaraVisualPhase` and run status.
- `@rive-app/canvas-advanced` gives us the Rive renderer and Rive RAF loop while keeping the brand bitmap stable.
- This avoids pretending a hand-authored `.riv` source exists when the repository currently only has raster brand assets.

## Why not front-end redraw the logo

The Klara mark remains the exact transparent bitmap asset. Rive only draws external light-field motion around it.

## Runtime behavior

- `KlaraRiveField.tsx` lazy-loads the Rive WASM only in the browser.
- Tests skip runtime initialization under Vitest/jsdom, so component tests stay deterministic. Vitest is run with one thread/no file parallelism because the WASM-enabled dependency is expensive to transform on this WSL workspace.
- Reduced motion disables the canvas field and leaves the static mark/stamp visible.
- The Rive runtime is code-split by Vite into a separate chunk.

## Follow-up

If a designer later exports a hand-authored `klara-presence.riv`, `KlaraRiveField` can be swapped to load that file while preserving the same component API.
