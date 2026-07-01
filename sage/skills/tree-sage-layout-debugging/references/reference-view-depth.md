# Reference View And Depth Notes

Use this reference when visual ordering, depth, or camera/view confidence is the suspected failure.

## View Reliability

- For oblique, bright, or cropped references, exact global front/back and left/right ordering may be unreliable.
- If global ordering is weak, prefer branch-local constraints and cross-branch relation checks over forcing all objects into one global sequence.
- Cross-branch comparisons such as left nightstand vs. far-right chest can be warning-level evidence, not automatic repair evidence.

## DepthAnything Usage

- Use monocular depth as a furniture-anchor profile, not raw global truth.
- Convert raw relative depth into a consistent `frontness` convention before comparing objects.
- Add the depth profile to the scene hypergraph or validation loop; a passive depth report will not repair drift.
- If the depth profile flags a final scene mismatch, run a render-depth review before hard repair: inspect the reference image, final render, reference bbox/crop, and depth-map evidence, then decide whether the issue is true layout depth drift or a monocular-depth artifact.
- Do not make plants or large soft furniture hard depth anchors. Plant crops include leaves/background gaps, and beds/sofas cover a large visible depth range.
- Do not let a second-stage foreground trim move side-wall storage along its wall tangent. East/west wall-backed wardrobes, dressers, chests, cabinets, bookcases, and sideboards should preserve their wall-local depth through room compaction, then be corrected by same-wall tangent/corner checks.
- Rerun per-wall relation audit after the final density/support/tabletop/collision pass. Earlier storage-corner and door/storage fixes are not reliable if later passes can still move objects.
- Same-wall window/storage proximity is not enough to force equal wall-tangent depth. If a dresser/cabinet appears under or beside a side-wall window but its reference bbox bottom and depth/frontness show it is closer to the camera than the window, skip window-cluster alignment and use bed-front/depth or explicit wall-local relation evidence instead.

## Same-Depth Bands

- Treat close back-wall depth differences as same-depth bands. A hard threshold that is too narrow creates visually pointless repairs.
- Use a wider same-depth tolerance for depth-frontness profiles than for bbox ordering.
- Use strict ordering only when the reference crop, object support, and local branch context agree.
- In oblique side-wall views, wall-plane objects and floor decor should not be forced into one local left/right tangent order just because their 2D bboxes are adjacent. A side-wall window/curtain branch can visually overlap a floor plant that belongs to a separate floor branch.
- For this filtering, classify wall-plane vs. floor-decor objects from id/category/agent semantics. Do not scan full descriptions, because relation phrases such as "plant near the right window" can falsely classify a floor plant as a wall-plane object.
- Coplanar window/curtain/rod front-back order on a side wall is usually a perspective artifact. Use dedicated wall-flush placement and curtain flanking logic, not generic depth/gap repair.
- In oblique bedroom references, tabletop front-back order among small items is weak evidence. Prefer support-surface packing, size checks, and collision checks unless the reference provides unusually clear depth evidence.

## Large Anchors

- Large soft anchors need depth slices and rear-contact evidence.
- A bed/sofa crop median is dominated by visible blanket or cushion area and can pull the whole object too far forward.
- For beds/sofas, inspect vertical image slices: rear/top slices explain wall or rear-furniture contact, lower/front slices explain foreground occlusion.
- Move a large object by matching its rear edge to the front edge of overlapping rear anchors only when the reference bbox shows horizontal overlap and near-contact.

## Pair And Gap Constraints

- Pair order is useful only when instance identity is reliable.
- If repeated objects are present, require explicit reference-instance mapping before enforcing strict pair order.
- Gap affinity is weaker than hard order. Use it to detect drift toward the wrong cluster, not to override a coherent branch without visual confirmation.
