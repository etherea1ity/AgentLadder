# Motion Agent Notes

## Findings
- Current motion is light but lacks reduced-motion handling.
- Existing visual direction is quiet paper/editorial; no spinners or game-like effects.

## Recommendation
- Use calm optical presence: weak halo, slow orbit glint, dust-like particles, completed flash.
- Keep particles under 8 visible; default 2-4.
- Disable rotating/drifting motion under prefers-reduced-motion.

## Risks
- PNG-only logo assets can fringe if scaled/animated too aggressively.
- Too much glow makes Klara feel like a sticker or game skill.

## Acceptance Focus
- Logo body is not rotated or redrawn.
- Motion uses opacity/transform only and does not block reading.
- Reduced motion leaves state understandable.

## Challenges
- Asset should provide alpha-clean mark or vector source later.
