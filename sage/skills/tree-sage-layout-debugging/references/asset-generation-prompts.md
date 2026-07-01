# Asset Generation Prompt Notes

Use this file only when editing Flow 2 asset prompts, deciding whether to regenerate an asset, or debugging Flux/Trellis2 reference-image inputs. General layout, support, and validation agents should not need it.

## Windows

Windows are not paintings or wall-art panels. They should read as thin architectural frame assemblies with glass panes, not as opaque slabs.

Prompt requirements:

- Ask for a `thin wall-mounted residential window frame assembly` with a continuous outer frame and muntins/dividers.
- Allow clear, frosted, or very pale lightly tinted glass panes.
- Keep depth shallow, but do not request a `single integrated backing plane`.
- Explicitly forbid opaque backing sheets, black solid backplates, wall slabs behind the window, freestanding bodies, and saturated background color visible inside the panes.

Avoid prompt phrases:

- `single integrated backing plane`
- `solid backing panel`
- `opaque backplate`
- `wall slab behind it`
- `flat panel asset` when the phrase causes Trellis2 to treat the panes as a filled board

Recommended Trellis2 prompt suffix:

```text
thin wall-mounted residential window frame assembly, continuous outer frame and muntins,
clear or very pale lightly tinted glass panes, readable front surface, very shallow depth,
no opaque backing plane, no black solid backplate, no wall slab behind it, no freestanding body,
no saturated background color visible inside the panes
```

Reference-image and alpha-mask checks:

- Inspect the isolated input image and the prepared RGBA/mask before trusting the GLB.
- The mask may include the frame and optional pale glass sheet, but it must not keep large saturated background rectangles inside the pane openings.
- If panes are open/transparent in the input image, the mask should not become one large solid foreground rectangle.
- If the prepared mask has irregular holes or a large filled panel where panes should be, regenerate or fallback before Trellis2 reconstruction.
- Do not infer a Trellis/GLB window's vertical axis only from raw trimesh bbox axes. Blender's glTF importer can already present the window upright even when raw local `z` is the thin pane axis. Confirm with rendered front/side views before changing `asset_axis_to_z`.

QA failure signs:

- Side render shows a thick black slab or opaque backplate behind the frame.
- Front render shows one dark irregular block instead of readable panes and muntins.
- Front render has internal floating specks, dirty pane blobs, or a frame split into hundreds/thousands of disconnected islands.
- The object passes single-component/thin-axis checks but looks like a dirty wall panel from an oblique scene camera.

Fallback guidance:

- Prefer a clean procedural/parametric window over a Trellis2 window that has a black backplate or unreadable pane geometry.
- Do not replace a readable Trellis2 window only because QA reports wall-thickness compression or a sill-like low component. Those are expected for wall-mounted windows; fallback only for strong failures such as excessive disconnected fragments, component-policy violations, opaque backplates, or unreadable pane/frame geometry.
- A simple procedural window can be acceptable if it has readable frame, sill, muntins, shallow wall depth, and no opaque backplate.
- Prompt fixes and alpha-mask fixes can remove the worst black backplate, but Trellis2 can still leave pane specks and fragmented frame islands. Treat this as an asset-generation failure, not a layout problem.
- For procedural fallback windows, prefer frame/muntin geometry without one continuous glass sheet. Transparent glass materials may export/render as a grey opaque rectangle and recreate the same slab-like failure mode.

## Doors And Closet Doors

Doors are floor-grounded wall panels. Unlike windows, a thin opaque panel is valid.

Prompt requirements:

- Use a front-facing thin slab/panel with visible door details.
- For closet doors, request paneled double-door surfaces, knobs/handles, and hinges if visible.
- Forbid freestanding cabinet bodies, wardrobe boxes, side walls, and deep furniture bodies.

Do not replace a readable Trellis2 door only because it needs wall-thin scaling. Treat thinness/axis compression as a placement issue unless the asset is fragmented, missing, unreadable, or has background/base artifacts.

## Curtains And Drapes

Curtains are fabric panels, not rigid wall slabs.

Prompt requirements:

- Ask for tall hanging fabric curtain/drape panels with visible folds.
- Avoid hard backing planes and board-like shapes.
- Use reference bbox vertical extent and paired-panel symmetry for final scale.

QA failure signs:

- One panel becomes much narrower than its paired panel.
- A generic wall-axis repair swaps width/length based only on raw local extents.
- The side render proves the curtain is physically sideways; otherwise do not apply generic wall-flat axis swaps.
