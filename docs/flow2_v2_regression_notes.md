# TreeSAGE Flow 2 Bedroom Regression Notes

This note records only patterns that were observed during the bedroom-scene iterations. It should not be treated as a generic indoor-layout rulebook.

## Accepted Baselines

Use the bedroom V2 result as the current visual baseline:

- Source: `/data/xy/SAGE_runs/tree_sage_bedroom_image/glb_v2_whitebase_assets`
- Restored copy: `/data/xy/SAGE_runs/tree_sage_bedroom_image/glb_v8_restored_v2`
- Main GLB: `/data/xy/SAGE_runs/tree_sage_bedroom_image/glb_v8_restored_v2/scene_tree_sage_flow2.glb`
- Main comparison image: `/data/xy/SAGE_runs/tree_sage_bedroom_image/glb_v8_restored_v2/reference_vs_render_restored_v2.png`

Treat V3, V4, V5, V6, and V7 as rejected regression attempts for this bedroom scene.

Current best local-repair candidate:

- Candidate: `/data/xy/SAGE_runs/tree_sage_bedroom_image/glb_v13_v2_bed_left_floor_lamp_corner_fix`
- Main GLB: `/data/xy/SAGE_runs/tree_sage_bedroom_image/glb_v13_v2_bed_left_floor_lamp_corner_fix/scene_tree_sage_flow2.glb`
- Main comparison image: `/data/xy/SAGE_runs/tree_sage_bedroom_image/glb_v13_v2_bed_left_floor_lamp_corner_fix/reference_vs_render_bed_left_floor_lamp_corner_fix.png`
- Change from V12: bed and bed-top objects shifted left by `0.15m`, while keeping the floor-lamp/right-wall branch correction.

## What V2 Preserved

V2 kept the scene as a coherent bedroom composition:

- The bed remained centered and near the back-wall furniture group.
- The two wardrobes stayed on the rear wall in the same left-to-right order as the reference.
- The right dresser, small right chest, floor lamp, mirror, and plants stayed as one right-side/back-right visual branch.
- The left nightstand stayed beside the bed instead of being pulled into an unrelated wall branch.
- The room dimensions stayed `width=5.5`, `length=4.8`.

Key V2 positions:

| Object | x | y | yaw | Note |
| --- | ---: | ---: | ---: | --- |
| `queen_bed` | 2.78 | 3.42 | 180 | central bed, stable baseline |
| `left_wardrobe` | 1.25 | 4.48 | 180 | rear-left wardrobe |
| `center_wardrobe` | 2.52 | 4.48 | 180 | rear-center wardrobe |
| `left_nightstand` | 0.72 | 2.55 | 180 | left bedside branch |
| `right_dresser` | 4.42 | 4.42 | 180 | right/back dresser branch |
| `small_right_chest` | 5.04 | 3.30 | 180 | right-side chest |
| `round_wall_mirror` | 4.58 | 4.78 | 270 | rear/right visual branch, wall attached |
| `floor_lamp` | 3.88 | 4.08 | 180 | behind/right of bed |
| `right_floor_plant` | 3.55 | 3.48 | 0 | between bed and right furniture |
| `left_floor_plant` | 0.46 | 3.40 | 0 | left bedside/back-left branch |

## Regression Pattern In V3-V7

The later versions did not fail because of one isolated pose error. They failed because new repair modules made hard structural edits from weak evidence, then later validators accepted physically stable but visually worse layouts.

Observed regressions:

- V3 moved the bed to the front (`queen_bed y=1.13`) and rotated it into a different visual pose.
- V4 moved the bed back into collision-prone rear space (`queen_bed y=3.65`) and failed aggregate collision.
- V5 and V6 continued moving major anchors while failing reference alignment.
- V6 physically passed after repairs, but only because objects were spread apart; it no longer matched the reference.
- V7 passed validators after disabling wall arbitration, but still did not recover the V2 visual composition.
- V3-V7 also changed important object scales. For example, the wardrobes dropped from V2 heights around `1.7-1.92m` to about `0.935m`, while some plants became furniture-sized. This made later collision and ordering repairs operate on a distorted scene.

Main cause:

- `oblique_wall_affinity_arbitration` treated image-edge bbox evidence as enough to rewrite wall relations. In an oblique bedroom reference, this is not reliable. It split coherent branches and caused later repair modules to rearrange furniture around the wrong wall.

Secondary causes:

- Back-to-wall pose logic was applied as a hard geometric correction before proving the target wall was correct.
- Effective yaw became hard to reason about because `yaw`, `front_yaw_offset_degrees`, and `footprint_yaw_offset_degrees` interact.
- Collision repair and MuJoCo stability were over-weighted. A non-colliding layout can still be visually wrong.
- Validators were too local: they checked pair/order/collision constraints but did not preserve the global composition from the reference.
- Agent wall classification was not reliable for this oblique image. The pose agent itself labeled the right dresser, mirror, small chest, and floor lamp as `wall_north`, so replacing that with bbox-edge heuristics was not a safe improvement.
- Scale normalization was allowed to alter visual anchors too much. Major objects must keep reference-level proportions before any collision or pose repair is trusted.

## Useful Local Fixes In V10-V13

These were the changes that improved the restored V2 baseline without destroying its composition:

- Bed front/back pose: changing `queen_bed yaw` from `180` to `0` fixed the visible head/foot reversal.
- Bed/cabinet collision: moving the bed forward fixed the collision while preserving bed scale. The accepted clearance check was bed rear `y=4.21` against wardrobe front about `y=4.23`.
- Right-side wall branch: `right_dresser` and `small_right_chest` were corrected to the east/right wall instead of the rear wall.
- Floor lamp: the lamp must be deepest in the right branch and occupy the east+north corner. Accepted ordering is `floor_lamp y=4.54 > right_dresser y=3.55 > small_right_chest y=2.35`.
- Bed horizontal placement: after the right branch was corrected, shifting the bed left by `0.15m` improved visual agreement without introducing overlaps.
- Left floor plant: the useful repair keeps it in the left bedside/back-left branch behind the nightstand. The missing constraint was `left_nightstand in_front_of left_floor_plant`; without it, validators accepted the plant in the foreground.
- Floor lamp scale and support: generic lamp normalization incorrectly shrank the floor lamp to a tabletop-lamp height. After restoring floor-lamp scale, it must remain floor-supported and `near` the east wall, not `support_id=wall_east` or hard-clamped like a dresser.

## Empirical Rules For The Executing Agent

1. Never rewrite support wall or branch membership from bbox edge alone.
   - Image-left/image-right near the edge is camera evidence, not wall-plane evidence.
   - Changing `wall_north` to `wall_east` or `wall_west` requires explicit multi-source support: reference crop, whole-image context, branch relation, and rendered candidate comparison.

2. Preserve branch identity before repairing individual relations.
   - The right dresser, small right chest, mirror, floor lamp, and nearby plants are one visual branch in this scene.
   - Do not split a branch just to satisfy a local wall or pair relation.

3. Do not accept a repair only because collisions disappear.
   - Collision-free and MuJoCo-stable is necessary, not sufficient.
   - A repair that reduces collision but worsens reference composition must be rejected.

4. Do not let local validators override the global reference composition.
   - Pair order, wall relation, pose review, support-surface snapping, and collision repair must be evaluated against the whole-scene reference render.
   - If the rendered comparison looks worse than V2, reject the change even when `global_validator_ok=true`.

5. Treat oblique reference images as low-confidence for depth and wall-plane inference.
   - Use branch-level relationships instead of global left/right/front/back when view readability is low.
   - Do not infer exact wall attachment from a single 2D bbox.

6. Separate yaw semantics from geometry transforms.
   - `yaw` is not the only facing direction.
   - Effective facing uses `yaw + front_yaw_offset_degrees + footprint_yaw_offset_degrees`.
   - Physical footprint uses `yaw + footprint_yaw_offset_degrees`.
   - Never add `front_yaw_offset_degrees` in Blender assembly; that double-applies front correction.

7. Run A/B acceptance against the V2 baseline before committing new repair modules.
   - Produce a candidate render from the same estimated reference camera.
   - Compare visually and through reference-composition constraints.
   - Only accept if the candidate is at least as coherent as V2 and improves the specific targeted issue.

8. Freeze or strictly gate major-anchor scale changes.
   - Wardrobes, beds, dressers, tables, cabinets, sofas, and other large anchors cannot be rescaled by a generic fallback if the reference clearly shows their relative sizes.
   - Do not run collision repair on a scene whose anchor scales are already wrong; fix scale first.

9. Experimental modules must default off.
   - `oblique_wall_affinity_arbitration` is experimental and must stay disabled unless explicitly requested.
   - Any module that can rewrite wall support, branch root, major-anchor order, or room axes must have an explicit enable flag and an acceptance gate.

10. User-confirmed facts are regression tests, not optional hints.
   - For this bedroom, the floor lamp is deeper than the two right cabinets and belongs at the back-right corner.
   - The right dresser and small right chest attach to the right wall, not the rear wall.
   - The left nightstand belongs beside the bed, not in an unrelated wall branch.
   - These checks must be preserved before another automatic repair is accepted.

11. Do not classify from full descriptive text when the text contains relation words.
   - `left_floor_plant` contains "beside left nightstand" in its description; using full text for category matching generated an invalid self relation.
   - Category/id/semantic class should drive object type decisions; descriptions should only provide placement evidence.

12. Separate `near wall` from `against wall` for floor decor.
   - Floor lamps and plants can be near a wall or corner without occupying the wall plane.
   - Hard wall clamp is appropriate for wardrobes/dressers/cabinets, but it can collide floor decor with wall-mounted mirrors or pictures.

## Required Acceptance Gate For Future Changes

Before accepting a new Flow 2 layout change for this scene, the agent must verify:

- It does not move `queen_bed` far from the V2 central/back composition unless the reference render proves improvement.
- It does not swap `left_wardrobe` and `center_wardrobe`.
- It does not split the right-side dresser/chest/mirror/lamp branch.
- It does not move the bed to the foreground just to satisfy collision or pair constraints.
- It does not shrink wardrobes or inflate plants enough to change the scene hierarchy.
- It does not pass solely on `global_validator_ok`, `aggregate_collision_ok`, or `mujoco_ok`.
- It produces a rendered comparison at least as visually coherent as `reference_vs_render_restored_v2.png`.

## Current Decision

Rollback target is V2 when broad repair modules regress the scene. V13 is the current best local-repair candidate. Future modules should be tested as isolated candidates against V2/V13, not stacked directly into the main flow.
