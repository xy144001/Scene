#!/usr/bin/env python3
"""Render SAGE scene and asset diagnostic views from Blender.

Run with:
  blender --background --python scripts/blender_render_sage_diagnostics.py -- ...
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Render visual diagnostics for a SAGE-style GLB scene.")
    parser.add_argument("--scene-glb", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--asset-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resolution", type=int, default=900)
    parser.add_argument("--skip-assets", action="store_true")
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def renderable_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type in TARGET_TYPES]


def mesh_bbox_world(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    corners: list[Vector] = []
    for obj in objects:
        if obj.type not in TARGET_TYPES:
            continue
        for corner in obj.bound_box:
            corners.append(obj.matrix_world @ Vector(corner))
    if not corners:
        raise RuntimeError("No renderable geometry found.")
    min_v = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    max_v = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return min_v, max_v


def look_at(camera_obj: bpy.types.Object, target: Vector) -> None:
    direction = target - camera_obj.location
    camera_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_world() -> None:
    world = bpy.data.worlds.new("DiagnosticWorld")
    world.use_nodes = True
    bpy.context.scene.world = world
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.96, 0.955, 0.94, 1.0)
    bg.inputs[1].default_value = 0.82


def add_area_light(name: str, location: tuple[float, float, float], energy: float, size: float) -> None:
    light_data = bpy.data.lights.new(name=name, type="AREA")
    light_data.energy = energy
    light_data.size = size
    light_data.size_y = size
    light_obj = bpy.data.objects.new(name, light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = location
    look_at(light_obj, Vector((0.0, 0.0, 0.0)))


def setup_lighting() -> None:
    add_area_light("KeyLight", (3.0, -4.0, 4.2), 4200.0, 5.0)
    add_area_light("FillLight", (-4.0, 2.5, 3.0), 1800.0, 6.0)
    add_area_light("TopLight", (0.0, 0.0, 5.0), 1400.0, 5.5)


def setup_render(output: Path, resolution: int) -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    if hasattr(scene, "eevee"):
        if hasattr(scene.eevee, "taa_render_samples"):
            scene.eevee.taa_render_samples = 32
        if hasattr(scene.eevee, "use_gtao"):
            scene.eevee.use_gtao = True


def add_camera(name: str, location: tuple[float, float, float], target: tuple[float, float, float]) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new(name)
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = location
    look_at(cam_obj, Vector(target))
    bpy.context.scene.camera = cam_obj
    return cam_obj


def render_current(output: Path, resolution: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    setup_render(output, resolution)
    bpy.ops.render.render(write_still=True)


def set_material_alpha_mode() -> None:
    for mat in bpy.data.materials:
        mat.blend_method = "BLEND"
        mat.use_screen_refraction = False


def is_room_shell(obj: bpy.types.Object) -> bool:
    name = obj.name.lower()
    data_name = obj.data.name.lower() if getattr(obj, "data", None) else ""
    return (
        name == "floor"
        or data_name == "floor"
        or name.startswith("floor.")
        or data_name.startswith("floor.")
        or name.startswith("wall_")
        or data_name.startswith("wall_")
    )


def set_room_shell_hidden(hidden: bool, hide_floor: bool = False) -> None:
    for obj in bpy.context.scene.objects:
        if obj.type not in TARGET_TYPES:
            continue
        if is_room_shell(obj) and (hide_floor or "floor" not in obj.name.lower()):
            obj.hide_render = hidden
            obj.hide_viewport = hidden


def object_bbox_by_keywords(keywords: tuple[str, ...]) -> tuple[Vector, Vector] | None:
    matched = []
    for obj in bpy.context.scene.objects:
        if obj.type not in TARGET_TYPES:
            continue
        text = f"{obj.name} {obj.data.name if getattr(obj, 'data', None) else ''}".lower()
        if any(keyword in text for keyword in keywords):
            matched.append(obj)
    if not matched:
        return None
    return mesh_bbox_world(matched)


def render_scene_views(scene_glb: Path, plan: dict, output_dir: Path, resolution: int) -> list[Path]:
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(scene_glb))
    set_material_alpha_mode()
    setup_world()
    setup_lighting()

    objects = renderable_objects()
    min_v, max_v = mesh_bbox_world(objects)
    center_v = (min_v + max_v) * 0.5
    extents = max_v - min_v
    width = max(float(extents.x), 1e-3)
    length = max(float(extents.y), 1e-3)
    height = max(float(extents.z), 1e-3)
    center = (float(center_v.x), float(center_v.y), float(center_v.z))
    diag = max(width, length, height)
    views: list[Path] = []

    set_room_shell_hidden(True)
    top = add_camera("SceneTopCamera", (center[0], center[1], float(max_v.z) + diag * 1.05), center)
    top.data.type = "ORTHO"
    top.data.ortho_scale = max(width, length) * 1.12
    top_path = output_dir / "scene_top.png"
    render_current(top_path, resolution)
    views.append(top_path)

    corner = add_camera(
        "SceneCornerCamera",
        (center[0] + width * 0.78, center[1] - length * 0.92, center[2] + height * 0.45),
        center,
    )
    corner.data.lens = 28
    corner_path = output_dir / "scene_corner.png"
    render_current(corner_path, resolution)
    views.append(corner_path)

    front = add_camera(
        "SceneFrontCamera",
        (center[0], center[1] - length * 1.15, center[2] + height * 0.20),
        (center[0], center[1], center[2] + height * 0.05),
    )
    front.data.lens = 34
    front_path = output_dir / "scene_front.png"
    render_current(front_path, resolution)
    views.append(front_path)

    desk_bbox = object_bbox_by_keywords(("desk",))
    if desk_bbox:
        desk_min, desk_max = desk_bbox
        desk_center = (desk_min + desk_max) * 0.5
        dx = float(desk_center.x)
        dy = float(desk_center.y)
        dz = float(desk_center.z)
        close = add_camera(
            "DeskCloseCamera",
            (dx + max(width, 1.0) * 0.18, dy - max(length, 1.0) * 0.35, dz + max(height, 1.0) * 0.18),
            (dx, dy, dz),
        )
        close.data.lens = 55
        close_path = output_dir / "scene_desk_close.png"
        render_current(close_path, resolution)
        views.append(close_path)

    set_room_shell_hidden(False)
    return views


def normalize_asset(objects: list[bpy.types.Object]) -> None:
    mesh_objects = [obj for obj in objects if obj.type in TARGET_TYPES]
    if not mesh_objects:
        raise RuntimeError("Imported asset contains no renderable objects.")
    min_v, max_v = mesh_bbox_world(mesh_objects)
    center = (min_v + max_v) * 0.5
    extents = max_v - min_v
    max_extent = max(float(extents.x), float(extents.y), float(extents.z), 1e-6)
    root = bpy.data.objects.new("AssetRoot", None)
    bpy.context.scene.collection.objects.link(root)
    imported_set = set(objects)
    root_candidates = [obj for obj in objects if obj.parent not in imported_set]
    for obj in root_candidates:
        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()
    root.location = -center
    root.scale = (1.35 / max_extent, 1.35 / max_extent, 1.35 / max_extent)


def render_asset_views(asset_dir: Path, plan: dict, output_dir: Path, resolution: int) -> list[Path]:
    views: list[Path] = []
    asset_output = output_dir / "assets"
    asset_output.mkdir(parents=True, exist_ok=True)

    for obj in plan.get("objects", []):
        object_id = str(obj.get("id"))
        asset_path = asset_dir / f"{object_id}.glb"
        if not asset_path.exists():
            continue
        clear_scene()
        bpy.ops.import_scene.gltf(filepath=str(asset_path))
        imported = list(bpy.context.scene.objects)
        normalize_asset(imported)
        setup_world()
        setup_lighting()

        front = add_camera("AssetFrontCamera", (2.2, -2.8, 1.45), (0.0, 0.0, 0.1))
        front.data.type = "ORTHO"
        front.data.ortho_scale = 1.95
        front_path = asset_output / f"{object_id}_front.png"
        render_current(front_path, max(520, resolution // 2))
        views.append(front_path)

        side = add_camera("AssetSideCamera", (2.8, 0.0, 1.45), (0.0, 0.0, 0.1))
        side.data.type = "ORTHO"
        side.data.ortho_scale = 1.95
        side_path = asset_output / f"{object_id}_side.png"
        render_current(side_path, max(520, resolution // 2))
        views.append(side_path)

    return views


def main() -> None:
    args = parse_args()
    if not args.scene_glb.exists():
        raise FileNotFoundError(f"Missing scene GLB: {args.scene_glb}")
    if not args.plan.exists():
        raise FileNotFoundError(f"Missing plan: {args.plan}")
    if not args.asset_dir.exists():
        raise FileNotFoundError(f"Missing asset dir: {args.asset_dir}")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scene_views = render_scene_views(args.scene_glb, plan, args.output_dir, args.resolution)
    asset_views = [] if args.skip_assets else render_asset_views(args.asset_dir, plan, args.output_dir, args.resolution)
    manifest = {"scene_views": [str(path) for path in scene_views], "asset_views": [str(path) for path in asset_views]}
    (args.output_dir / "render_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
