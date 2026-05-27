# Klara Assets

## Source

The current repository provided PNG assets in `apps/web/public/brand/`:

- `klara_symbol_exact_cut.png` — 256×256 RGBA mark-only asset.
- `klara_favicon_exact_cut.png` — 256×256 RGBA favicon/symbol duplicate.
- `klara_navbar_exact_cut.png` — 353×93 RGBA horizontal lockup.
- `klara_poster_lockup_cut.png` — 1098×996 RGBA poster/hero reference.

## Normalized Public Paths

Created under `apps/web/public/brand/klara/`:

- `klara-lockup-light.png` from `klara_navbar_exact_cut.png`.
- `klara-mark-light.png` from `klara_symbol_exact_cut.png`.
- `klara-mark-light@2x.png` from `klara_symbol_exact_cut.png` as current retina fallback.
- `klara-fallback-static.webp` currently uses the same raster source as a fallback placeholder because WebP encoding tools are not available in this environment.
- `klara-poster-lockup-reference.png` from `klara_poster_lockup_cut.png` for the home hero/reference.

## Processing Notes

No CSS/SVG redraw was produced. No traced SVG is used because the current available source is raster-only and an inaccurate vector trace would violate brand fidelity. No `.riv` was generated because there is no Rive source file or approved vector layer package.

## Limitations

- Raster assets may show small-size aliasing/fringing compared with a true vector export.
- The navbar lockup source has tight bounds; avoid adding strong glow directly on that image.
- The poster lockup is brand art/reference and not a clean layout-neutral lockup.

## Recommendation

Export final production assets from the design source file:

1. Clean SVG mark with approved geometry.
2. Padded transparent PNGs at 1x/2x/3x.
3. Separate favicon simplified for 16/24/32px.
4. Rive file containing only optical layers: halo, orbit ring, state ring, satellites, dust shimmer.
