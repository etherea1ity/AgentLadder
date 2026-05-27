# Asset Agent Notes

## Findings
- Current assets are PNG only. Best mark-only asset: `klara_symbol_exact_cut.png` (256x256 RGBA transparent).
- Best horizontal lockup: `klara_navbar_exact_cut.png` (353x93 RGBA).
- Poster lockup is brand art/reference, not a clean reusable UI lockup.

## Recommendation
- Create stable public paths under `apps/web/public/brand/klara/`.
- Use PNG fallback now; request source vector later.
- Do not force SVG if tracing is not faithful.

## Risks
- Raster logo may blur/fringe at tiny favicon sizes or under dark-mode transforms.
- Navbar bottom may be clipped if used without padding.

## Acceptance Focus
- Mark-only has transparent background and no KLARA wordmark.
- Assets are centralized in `public/brand/klara/`.
- Docs record source limitations and next export recommendation.

## Challenges
- Motion should not rotate the raster mark itself.
