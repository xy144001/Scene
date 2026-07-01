#!/usr/bin/env python3
"""Render four local-axis views for selected SAGE assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}
VIEW_SPECS = {
    "+x": ((2.8, 0.0, 1.25), (0.0, 0.0, 0.18)),
    "-x": ((-2.8, 0.0, 1.25), (0.0, 0.0, 0.18)),
    "+y": ((0.0, 2.8, 1.25), (0.0, 0.0, 0.18)),
    "-y": ((0.0, -2.8, 1.25), (0.0, 0.0, 0.18)),
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Render asset turntable views.")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--asset-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--object-ids", required=True)
    parser.add_argument("--resolution", type=int, default=520)
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
    return (
        Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners))),
        Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners))),
    )


def look_at(camera_obj: bpy.types.Object, target: Vector) -> None:
    direction = target - camera_obj.location
    camera_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_world() -> None:
    world = bpy.data.worlds.new("TurntableWorld")
    world.use_nodes = True
    bpy.context.scene.world = world
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.965, 0.96, 0.94, 1.0)
    bg.inputs[1].default_value = 0.85


def add_area_light(name: str, location: tuple[float, float, float], energy: float, size: float) -> None:
    light_data = bpy.data.lights.new(name=name, type="AREA")
    light_data.energy = energy
    light_data.size = size
    obj = bpy.data.objects.new(name, light_data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    look_at(obj, Vector((0.0, 0.0, 0.0)))


def setup_lighting() -> None:
    add_area_light("KeyLight", (3.2, -3.5, 4.0), 4200.0, 4.5)
    add_area_light("FillLight", (-3.2, 3.0, 3.2), 1800.0, 5.5)
    add_area_light("TopLight", (0.0, 0.0, 4.8), 1200.0, 5.0)


def setup_render(output: Path, resolution: int) -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 32


def add_camera(name: str, location: tuple[float, float, float], target: tuple[float, float, float]) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new(name)
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = location
    look_at(cam_obj, Vector(target))
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 1.85
    bpy.context.scene.camera = cam_obj
    return cam_obj


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


def render_asset(asset_path: Path, object_id: str, output_dir: Path, resolution: int) -> dict[str, str]:
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(asset_path))
    imported = list(bpy.context.scene.objects)
    normalize_asset(imported)
    setup_world()
    setup_lighting()
    paths: dict[str, str] = {}
    object_dir = output_dir / object_id
    object_dir.mkdir(parents=True, exist_ok=True)
    for axis, (location, target) in VIEW_SPECS.items():
        camera = add_camera(f"Camera_{axis}", location, target)
        camera.data.ortho_scale = 1.85
        output = object_dir / f"{axis.replace('+', 'plus_').replace('-', 'minus_')}.png"
        setup_render(output, resolution)
        bpy.ops.render.render(write_still=True)
        paths[axis] = str(output)
    return paths


def main() -> None:
    args = parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    valid_ids = {str(obj.get("id")) for obj in plan.get("objects", []) if isinstance(obj, dict)}
    requested = [item.strip() for item in args.object_ids.split(",") if item.strip()]
    object_ids = [object_id for object_id in requested if object_id in valid_ids]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"views": {}, "missing": []}
    for object_id in object_ids:
        asset_path = args.asset_dir / f"{object_id}.glb"
        if not asset_path.exists():
            manifest["missing"].append(object_id)
            continue
        manifest["views"][object_id] = render_asset(asset_path, object_id, args.output_dir, args.resolution)
    (args.output_dir / "asset_turntable_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
