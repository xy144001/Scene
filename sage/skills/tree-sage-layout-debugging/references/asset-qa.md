# Asset QA Notes

Use this reference when layout is plausible but an object looks unreadable, fragmented, has a white base, has the wrong generator route, or cannot support reliable pose judgement.

Prompt-construction rules live in `asset-generation-prompts.md`; this file is for QA and accept/regenerate/fallback decisions.

## Provenance

- Do not infer generator provenance from directory names such as `assets_trellis2_cleaned`.
- Inspect each asset metadata `source` and `route`.
- Include an asset source report in summaries so Trellis2, parametric, procedural, and fallback assets are visible.

## Visual QA Over Axis QA

- Single-component and axis checks are not enough for flat wall assets.
- Windows, curtains, doors, mirrors, and wall art can pass thin-axis checks but render as black panels, fragmented pieces, or unreadable blocks.
- Include these assets in visual QA or route simple wall-plane objects to a procedural fallback.
- Curtains and drapes are easy to misread from raw mesh extents: a Blender-imported Trellis2 curtain can render upright while raw local bounds look z-thin. Do not apply generic z-thickness wall-axis remapping to curtain/drape assets unless a direct Blender render proves the import orientation is wrong.
- Curtain/drape layout scale should use the reference bbox vertical extent plus a semantic panel prior. Generic hanging defaults can make correct assets look like tiny high strips even when axis QA passes.
- Paired curtain panels are a symmetry check. If one panel becomes much narrower than the other after layout, suspect axis-repair dimension swapping before blaming Trellis2. Preserve the scale-prior width/height for both panels and only clamp wall-normal thickness.

## Doors And Flat Wall Objects

- Prompt flat wall-panel assets explicitly: very thin slab/panel, no cabinet body, no freestanding box.
- If a wall-attached asset needs extreme axis compression, treat it as a failed asset prompt or route, not as layout pose.
- Closet doors should be thin panels in the wall plane; do not accept a generated full wardrobe body as a door.

## White Bases And Cutouts

- White bases under isolated-object inputs are invalid when they are generator background remnants.
- Legal white geometry: actual lampshades, ceramics, drawers, cushions, pots, visible shelves, or deliberate object material.
- Illegal white geometry: oval/circular floor pads, rectangular plinths, shadow plates, image-background slabs, or support plates not present in the reference.
- Detect white bases before Trellis2 reconstruction when possible; repair or regenerate the input image rather than cleaning only the final mesh.

## Plant And Decor QA

- Upright bbox is not enough for tabletop plant QA. A plant can be z-up by bbox and still read as a sideways leaf cluster.
- For tabletop plants, require visible pot/stem/foliage hierarchy. If unclear, use a clearer upright pot fallback instead of rotating blindly.
- Plant crops are weak depth anchors because leaves and transparent gaps mix foreground/background.

## Soft Textiles

- Pillows, cushions, blankets, throws, quilts, duvets, and loose bedding are not separate Flow 2 assets under the current rigid-layout scope.
- If visible bedding is missing, repair the parent bed/sofa prompt or reference input. Do not route separate pillow/throw assets through Trellis2, parametric fallback, support snapping, or collision repair.
