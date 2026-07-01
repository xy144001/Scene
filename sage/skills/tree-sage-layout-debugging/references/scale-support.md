# Scale And Support Notes

Use this reference when objects look physically valid but too large, too small, floating, collapsed, or detached from their support branch.

## Scale Priors

- Restore scale before wall, collision, pair-order, or branch repair.
- Accepted `scene_plan.json` dimensions can be stronger scale priors than a current generated `scene_graph.json`, but only use accepted baselines when the task allows them.
- Do not classify scale bounds from full object descriptions or ids alone.
- Category and semantic class should drive scale type. Description text is fallback evidence after incompatible classes are excluded.
- Relationship words in asset prompts can pollute identity. A plant/lamp/clock "on a nightstand" is still a tabletop child, not a nightstand.
- ID support anchors also pollute identity. Names like `dresser_books`, `book_stack_on_dresser`, `photo_on_right_nightstand`, and `small_photo_on_left_nightstand` describe support/location, not furniture class.
- If category or agent semantics say `books`, `picture frame`, `photo`, `tabletop_flat`, `tabletop_upright`, or `tabletop_child`, classify as tabletop small/decor before scanning ids for `dresser`, `nightstand`, `cabinet`, or `bedside`.
- Reference bbox scale may only adjust tabletop books/photo/frame/clock/decor within small-object and support-surface bounds. It must not promote these objects to dresser/nightstand-sized dimensions.
- False matches observed: `bedroom`, `bedside`, and `behind the bed` triggered bed-sized bounds; `wardrobe_top_plant` triggered wardrobe bounds.
- False matches observed: `right_nightstand_books` became a nightstand-sized book stack, `framed_photo_on_dresser` became dresser-sized, and `small_photo_on_left_nightstand` became a half-meter nightstand-scale frame even though agent semantics were tabletop-correct.
- Generic `lighting` is not the same as `floor_lamp`; table lamps must keep tabletop lamp bounds.
- Desks with a small drawer are still desks/table anchors. Match `desk`/`table_anchor` before drawer/cabinet heuristics; otherwise a study desk can be scaled like a nightstand.
- A bed that dominates the reference bbox should not use the generic bed prior even when the prompt omits queen/king/full terms. Use the dominant bbox as evidence for a large bed prior.
- If a bookcase/bookshelf/shelving bbox touches the image boundary, treat its bbox as a cropped visible slice. Preserve normalized scene-graph dimensions or clamp conservatively; do not inflate it to a full tall-bookcase semantic prior from the visible slice alone.
- Inspect `object_scale_prior_report.json` after any scale change. A green validator can still hide a scale-prior bug.

## Support Surfaces

- Current Flow 2 scope is rigid or approximately rigid layout. Pillows, cushions, duvets, quilts, blankets, bed throws, and similar soft textiles should be integrated into the bed/sofa asset prompt and description, not emitted as separate scene objects.
- Do not restore soft bed/sofa textile objects from an old `scene_plan.json` scale prior. If an older baseline has pillow/throw children, treat them as superseded details unless the user explicitly asks for separate soft-object handling.
- Beds still need accurate parent support for rigid tabletop/headboard decor if present, but soft bedding should not create support-tree children, tabletop packing jobs, collision-repair targets, or asset-generation requests.

## Tabletop Objects

- Small tabletop identity overrides support words. An `alarm_clock` described as on a nightstand is a tabletop small object, not a nightstand.
- Scale-prior support restore can revive obsolete bedside-table children. After restoring old supported children, run a reference-visible tabletop audit before building the support tree; the reference should decide left/right nightstand contents.
- Tabletop packing must use rotated world footprint. If support yaw is `90` or `270`, raw width/length are not world x/y.
- Support-surface snapping should set z and clamp truly out-of-bounds x/y. It must not recenter every child after tabletop packing.
- Bedside/nightstand tabletop children may preserve carefully packed edge positions, but shelf/bookcase children should not inherit that exception. If a shelf/top child is larger than the inset support interval, center it on the surface so coverage ratio passes.
- Tabletop packing reports must fold every failed child/support `check` into the top-level `ok`. A report with `checks[].ok=false` but `ok=true` is a validator bug, not an acceptable pass.
- When tabletop siblings nearly fit, reduce the visible gap down to the configured minimum before shrinking objects. If only some children are shrinkable, compute fit scale from fixed-width plus shrinkable-width terms; do not use a naive `available / needed` scale while leaving lamps fixed.

## Rugs And Underlays

- Floor coverings must be classified before relational bed words. A rug described as under the bed is still a `floor_covering`.
- Rugs/carpets are thin visual floor layers, not ordinary support-tree parents.
- Furniture may partly overlap a rug and partly overlap exposed floor. Keep beds, sofas, desks, chairs, and cabinets floor-supported even when the reference says they are "on" a rug.
- Use rug relations for visual underlay alignment and scale only. Do not constrain a large object's support bounds, x/y, or scale from the rug footprint.
- For bed/sofa underlays, fit the rug to the visible/front under-bed region when the reference only shows the rug at the foot/front. Do not expand the rug to cover the full hidden footprint unless the reference clearly shows that.
- Keep rug thickness thin and visual: normally about 0.02m-0.05m. Minor geometric overlap between the rug volume and furniture feet is acceptable; it should not create a support-tree failure.

## Windows And Sills

- A window with a visible sill can be a horizontal support for a small plant/decor object. The expected support z should use the sill surface height near the bottom of the window, not the top of the window bbox.
- Keep the support-height validator and support-surface registry consistent. A correct `plant_on_window_sill` placement should not fail just because one path still computes support height as `window.z + window.height`.
