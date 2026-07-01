# Bedroom Regression Notes

These notes came from the bedroom iterations where an early coherent layout regressed after broad wall/depth repairs, then partially recovered through local fixes.

## Baseline Preservation

- Do not rewrite wall support from bbox edge alone. In V3-V7, edge-based oblique wall affinity split a coherent right-side branch and made the layout worse.
- Do not stack broad repairs after a good baseline. Useful bedroom fixes were local: bed yaw, bed depth, slight bed left shift, right-wall cabinet branch, floor-lamp corner placement, and bedside support/pose.
- User-corrected visual facts should become regression checks before another broad automatic repair.
- A second-round density/room-size refiner is useful for visibly sparse renders, but it must be gated by current geometry. Render/reference comparison can correctly ask to shrink the room while the current first-round plan still has latent collision or same-wall spacing problems.
- Keep small visual refiner prompts inline. A long density-refiner prompt that made Codex read a saved request file timed out in one full run; compacting the prompt to main anchors and omitting supported tabletop children returned quickly.
- Room compaction should preserve first-round layout structure. Do not uniformly scale every object center; move wall-normal coordinates with the changed room boundary while preserving same-wall tangent spacing and most lateral/free-object spacing unless room bounds force a clamp.
- After any density compaction candidate, rebuild validation and MuJoCo before accepting it. Roll back if collision count or physics displacement gets worse.

## Bedroom Branch Facts

- `right_dresser`, `small_right_chest`, `round_wall_mirror`, `floor_lamp`, and nearby plants are a coherent right-side/back-right branch.
- `floor_lamp` should be deeper than the two right cabinets and sit near the back-right corner, with a small inset allowed.
- The two right cabinets attach to the right wall, not the rear wall, in the accepted bedroom view.
- The left nightstand belongs to the bed branch. Do not pull it into an unrelated wall branch.
- A nightstand near the side edge is not automatically part of a far-side wardrobe or door branch.

## Bed And Bedside Tables

- Bed front/back pose must be verified with effective yaw and final assembly behavior. Do not double-apply `front_yaw_offset_degrees` in Blender assembly.
- Back-wall bed/sofa pose is not fixed until the visible GLB is checked. Validators can pass when the footprint bbox is correct but the Trellis2 raw bed mesh has its horizontal long axis on local X while the target scene dimensions store bed length on local Y. In that case, repair `asset_local_yaw_offset_degrees` after asset generation and again after reused pose priors; for north-wall beds in the current convention this is typically `270`.
- Reused asymmetric bed assets may need source asset-local coordinate metadata such as `front_yaw_offset_degrees`, `footprint_yaw_offset_degrees`, and `asset_axis_to_z` restored late in the flow. Do not copy old scene `yaw`, position, or scale unless an explicit accepted-scene prior mode is requested; those must be re-estimated from the current reference.
- Reused pose priors can reset a corrected `asset_local_yaw_offset_degrees` back to an older bad value. Any mesh-local axis repair that depends on the current GLB extents must run after `post_asset_reused_asset_pose_prior`, not only during early pose review.
- Same-semantic bed assets can have different generated local front axes. If `asset_canonical_front_report` says one bed is `+x` and another is `-y`, do not accept `asset_local_yaw_offset_degrees=0` for both just because their wide axis is tangent to the wall; use canonical-front evidence when the headboard geometry probe is low-confidence.
- If the headboard geometry probe is low-confidence, a high-confidence canonical-front axis can repair the visible bed/sofa local yaw, but only if the candidate `asset_local_yaw_offset_degrees` keeps the raw wide axis tangent to the contacted wall. Do not trade a correct wall footprint for a visually correct front.
- When constraining a bed/sofa to a wall, solve the visible effective front direction and the physical footprint long axis together. A late effective-yaw edit must not rotate the footprint sideways.
- Beds against a back wall need explicit rear-edge grounding, not only rear furniture anchors.
- If no rear floor anchor exists, an `against_wall` bed relation still needs the rear edge grounded near the wall.
- Multiple beds sharing the same wall should share the same wall-contact line even when the spatial-order agent omits a same-row group. Build a fallback same-wall bed row from wall relations before using pair-order repair.
- A shared nightstand between two beds is not part of the bed-row wall-contact line. Multi-bed row alignment may set its lateral position between the beds, but a shared-bedside depth rule should own its y/depth placement. Do not let these two repairs alternate on the same object across final passes.
- In multi-bed rows, shared bedside tables may participate in lateral spacing so beds leave a gap for them, but they must not be snapped to the same wall-contact y/x line as the beds.
- Single-bed visual branch shifts must not run on multi-bed rows. If a scene has multiple bed/sofa anchors, preserve the row as a unit; do not move one bed together with the shared nightstand/rug while leaving the other bed behind.
- Bed/cabinet collision was better solved by moving the bed forward until the rear edge just clears wardrobe fronts, not by shrinking the bed.
- Bedside tables belong to the bed branch. If the bed moves, realign bedside tables to the bed side/depth and move supported children with them.
- Bedside tables should not be absorbed into side-wall storage branch repair or generic side-wall rewriting.
- For bed headboards against `wall_north`, bedside drawer/front effective yaw should point toward the room (`270` in the current world convention).
- Final pose feedback must not roll back correct bedside drawer fronts because of unrelated soft validation warnings. If the pose creates collision, first try pose-aware local placement clearance.

## Doors, Wall Panels, And Side-Wall Furniture

- Wall-mounted doors are thin panels, not freestanding cabinets. If a prompt produces a cabinet body and then compresses it onto a wall, treat it as an asset route/prompt failure.
- Wall-mounted or closet doors are floor-grounded wall panels. Their bottom edge should touch the floor while the broad face stays flush with the wall; do not place them like paintings, mirrors, or windows floating at image-bbox center height.
- Windows can provide a shallow sill support surface for small plants/decor. A `plant_on_window_sill` object should snap to that sill surface instead of floating at a wall-bbox center.
- Thin wall layers such as curtains, sheers, and windows may overlap wall-flush bookcases or storage by only wall-layer thickness. Treat this as contact/tolerated layering, not a hard floor-furniture collision, when the overlap is mainly along the wall normal.
- A window with paired curtains and a curtain rod is one wall fixture assembly. After generic same-wall ordering or collision repair, re-lock the assembly so the window is between the two curtain panels and the rod spans the whole group. Do not use curtain-panel `on curtain_rod` support as a support-tree edge; keep it as a functional/visual relation so panels are not counted both as rod descendants and wall siblings.
- Wall-flat assets are legitimate broad thin geometry, but do not use one protection rule for every category. Doors, curtains, mirrors, posters, paintings, and wall art should not use broad-thin artifact cleanup; otherwise the cleaner can delete the actual panel/frame and leave a fragmented-looking asset. Windows are the exception: Trellis2 often adds extra glass/blind/background sheets, so window assets should still run broad-thin fragment cleanup and be validated by direct asset render plus final wall render.
- Window cleanup only works when the bad sheet is a separate component. If the bad blinds/frame/protrusion is one connected mesh and `asset_cleanup_report` shows `removed_components=0`, treat it as an asset candidate failure. Use a better historical/regenerated Trellis2 window or rerun the window prompt; do not keep tuning layout to hide a bad single-mesh window.
- High-confidence final pose feedback for wall-attached panels should survive thin-layer collision false positives when the requested effective yaw points into the room from the attached wall. This applies to windows, doors, mirrors, and wall art whose fronts are visibly reversed or blank because the back side is showing.
- Side-wall furniture depth is weak evidence in oblique references. Use window alignment, wall tangent order, support/tabletop relations, bbox bottom, and reference-depth/frontness as competing cues; do not move a side-wall dresser far toward the camera or lock it to a window segment unless the endpoint/depth evidence agrees.
- When a wall-attached object and a floor storage object share the same side wall, support alone does not determine tangent depth. Use reference-depth ordering if it is clear.
- High-confidence `against_wall` floor storage must be re-clamped to the wall after late order, collision, pose, and layout-polish repairs. Resolve conflicts along the wall tangent; do not let generic left/right ordering against doors, windows, curtains, mirrors, or wall art pull wardrobes/dressers/cabinets away from the wall plane.
- Before support-tree construction, synchronize `agent_semantics.wall_relation`, wall relations, and `pose_constraints.wall_id`. A side-wall object with `wall_relation=wall_east` but `pose_constraints.wall_id=wall_north` will be packed against one wall and oriented for another.
- For side-wall floor anchors such as wardrobes, dressers, bookcases, desks, and cabinets, do not assume the back face contacts the wall. If `front_yaw_world` is normal to the wall and points into the room, use back/front wall contact and keep the long axis tangent to the wall. If `front_yaw_world` is tangent to the wall, infer side-face wall contact and allow the long axis to run along the wall normal. This prevents visible drawer/door/handle faces from being rotated away merely because the object is near a side wall.
- For wall-attached and floor-storage objects on the same side wall, DepthAnything confidence can be too low for doors/windows. Use bbox bottom as a weak fallback tangent-depth cue, but keep it lower priority than explicit support and same-wall adjacency constraints.
- Same-wall door/storage tangent separation should classify `closet door` / `closet_door` as a real room door for wall-local depth auditing. Do not reject it merely because the text contains `closet`; only wardrobe/closet furniture should be excluded from door rules.
- If a reference describes a double closet door as `closet_door_left` and `closet_door_right` with overlapping/adjacent bboxes, merge the panels into one closet-door assembly before layout. Otherwise each full door slab gets independently scaled and moved, occupying excessive wall tangent/depth and destabilizing nearby dresser/storage placement.
- Correct same-wall order is not enough for doors and nearby storage. If the reference bboxes overlap strongly along the side-wall depth image axis, enforce a maximum wall-tangent gap as well as minimum clearance so the door and dresser/cabinet stay depth-close instead of drifting to opposite ends of the wall.
- A side-wall dresser/chest directly under a same-wall window may belong to that window/curtain wall segment, but this is not automatic. In `img0610_113657`, using bed-front depth alignment or treating curtains/windows as objects that require wall-tangent separation pushed `left_dresser` to the wrong depth; later runs also showed that loose window/curtain slots can over-extend the dresser. Prefer same-wall window bbox overlap/center alignment only when depth/frontness and endpoint-agent relations agree, then let support/tabletop children follow the storage.
- Curtains/windows and floor storage can visually share the same side-wall segment. Treat thin wall layers as wall-normal layering unless there is a clear tangent-order cue; do not force a dresser away only because its bbox overlaps a curtain or window in wall-tangent coordinates.
- Semantic wall attachment must be converted into actual support relations before `build_support_tree`. A framed artwork can have `agent_semantics.wall_relation.mode=attached` and `support_hint=wall_north`, but if no `attached_to wall_north` relation exists, the support tree can still default it to `floor`, leaving the final object at `z=0`.
- For left/right wall dressers and cabinets, distinguish logical front reports from real GLB pose. If canonical-front detection says the drawer/handle face is local `-y`, later storage-front repair must keep `front_yaw_offset_degrees` equal to the canonical visual offset and rotate the render yaw/footprint to satisfy the target front. Rewriting `front_yaw_offset_degrees` to make `_effective_yaw` pass can still render the mesh sideways.
- In oblique references, `visible_front_direction=camera` for a side-wall dresser/cabinet is often a perspective cue, not a physical side-face-contact cue. If the storage bbox is not on the image edge, do not infer `left_side/right_side` wall contact solely from `front_yaw_world=270`; prefer back-contact with the long axis tangent to the side wall unless stronger handle/side evidence exists.

## Bedding And Decor

- Flow 2 bedroom layout is rigid or approximately rigid. Pillows, cushions, blankets, throws, quilts, duvets, and loose bedding should be represented as visual details of the bed/sofa asset, not separate scene objects.
- Once soft textiles are merged into a parent bed/sofa description, words like `pillow`, `throw`, and `blanket` must not make bed/sofa detectors reject the parent object.
- Do not restore pillow/throw children from older accepted baselines when rerunning the current pipeline. Merge their visual evidence into the parent bed/sofa `description` and `asset_prompt`.
- If a bed asset misses visible pillows or bedding, fix the parent bed asset prompt or input image. Do not add separate soft-object layout branches to compensate.
