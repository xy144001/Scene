#!/usr/bin/env python3
"""Render single-asset yaw candidates from the estimated reference camera."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Render single-asset pose candidate images.")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--asset-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--object-ids", required=True)
    parser.add_argument("--yaws", default="0,45,90,135,180,225,270,315")
    parser.add_argument("--camera", choices=("front_high", "front_left_high", "front_right_high"), default="front_high")
    parser.add_argument("--resolution-x", type=int, default=1100)
    parser.add_argument("--resolution-y", type=int, default=900)
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def look_at(obj: bpy.types.Object, target: tuple[float, float, float] | Vector) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_world() -> None:
    scene = bpy.context.scene
    world = bpy.data.worlds.new("PoseCandidateWorld")
    world.color = (0.02, 0.02, 0.02)
    scene.world = world
    bpy.ops.object.light_add(type="AREA", location=(3.5, 2.5, 5.5))
    key = bpy.context.object
    key.name = "PoseCandidateKeyLight"
    key.data.energy = 850
    key.data.size = 6.0
    bpy.ops.object.light_add(type="AREA", location=(-2.5, -3.5, 4.2))
    fill = bpy.context.object
    fill.name = "PoseCandidateFillLight"
    fill.data.energy = 360
    fill.data.size = 5.5


def setup_render(output: Path, resolution_x: int, resolution_y: int) -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = int(resolution_x)
    scene.render.resolution_y = int(resolution_y)
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 32


def add_camera(plan: dict, mode: str) -> bpy.types.Object:
    room = plan.get("room") if isinstance(plan.get("room"), dict) else {}
    width = float(room.get("width", 7.0) or 7.0)
    length = float(room.get("length", 5.0) or 5.0)
    height = float(room.get("height", 2.7) or 2.7)
    target = (width * 0.50, length * 0.52, height * 0.32)
    if mode == "front_left_high":
        location = (width * 0.30, -length * 1.04, height * 2.05)
    elif mode == "front_right_high":
        location = (width * 0.70, -length * 1.04, height * 2.05)
    else:
        location = (width * 0.50, -length * 1.08, height * 2.05)
    cam_data = bpy.data.cameras.new("EstimatedReferenceCamera")
    cam = bpy.data.objects.new("EstimatedReferenceCamera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = location
    look_at(cam, target)
    cam.data.type = "PERSP"
    cam.data.lens = 32
    cam.data.sensor_width = 32
    bpy.context.scene.camera = cam
    return cam


def imported_objects(before: set[bpy.types.Object]) -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj not in before]


def mesh_bbox_world(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    corners: list[Vector] = []
    for obj in objects:
        if obj.type not in TARGET_TYPES:
            continue
        for corner in obj.bound_box:
            corners.append(obj.matrix_world @ Vector(corner))
    if not corners:
        raise RuntimeError("Imported asset has no renderable geometry.")
    min_v = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    max_v = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return min_v, max_v


def axis_to_z_matrix(axis_to_z: int, axis_sign: float = 1.0) -> Matrix:
    sign = -1.0 if float(axis_sign) < 0.0 else 1.0
    if axis_to_z == 0:
        if sign < 0.0:
            return Matrix(((0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        return Matrix(((0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    if axis_to_z == 1:
        if sign < 0.0:
            return Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, -1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        return Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    return Matrix.Identity(4)


def parent_roots(objects: list[bpy.types.Object], root: bpy.types.Object) -> None:
    imported_set = set(objects)
    root_candidates = [obj for obj in objects if obj.parent not in imported_set]
    for obj in root_candidates:
        world = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_world = world


def candidate_plan_object(obj_plan: dict, effective_yaw: float) -> dict:
    candidate = dict(obj_plan)
    front_offset = float(candidate.get("front_yaw_offset_degrees", 0.0) or 0.0)
    footprint_offset = float(candidate.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
    candidate["yaw"] = (float(effective_yaw) - front_offset - footprint_offset) % 360.0
    return candidate


def transform_imported_asset(objects: list[bpy.types.Object], obj_plan: dict) -> None:
    axis_matrix = axis_to_z_matrix(
        int(obj_plan.get("asset_axis_to_z", 2)),
        float(obj_plan.get("asset_axis_to_z_sign", 1.0) or 1.0),
    )
    if axis_matrix != Matrix.Identity(4):
        for obj in objects:
            if obj.type in TARGET_TYPES:
                obj.matrix_world = axis_matrix @ obj.matrix_world

    asset_local_offset = float(obj_plan.get("asset_local_yaw_offset_degrees", 0.0) or 0.0)
    if abs(asset_local_offset) > 1e-6:
        local_front_matrix = Matrix.Rotation(math.radians(asset_local_offset), 4, "Z")
        for obj in objects:
            if obj.type in TARGET_TYPES:
                obj.matrix_world = local_front_matrix @ obj.matrix_world

    renderables = [obj for obj in objects if obj.type in TARGET_TYPES]
    min_v, max_v = mesh_bbox_world(renderables)
    center = (min_v + max_v) * 0.5
    extents = max_v - min_v
    dims = obj_plan["dimensions"]
    target = Vector((float(dims["width"]), float(dims["length"]), float(dims["height"])))
    scale = Vector(
        (
            target.x / max(float(extents.x), 1e-6),
            target.y / max(float(extents.y), 1e-6),
            target.z / max(float(extents.z), 1e-6),
        )
    )
    root = bpy.data.objects.new(f"{obj_plan['id']}_root", None)
    bpy.context.scene.collection.objects.link(root)
    parent_roots(objects, root)
    yaw = math.radians(float(obj_plan.get("yaw", 0.0) or 0.0) + float(obj_plan.get("footprint_yaw_offset_degrees", 0.0) or 0.0))
    root.matrix_world = (
        Matrix.Translation((float(obj_plan["x"]), float(obj_plan["y"]), float(obj_plan.get("z", 0.0))))
        @ Matrix.Rotation(yaw, 4, "Z")
        @ Matrix.Translation((0.0, 0.0, target.z / 2.0))
        @ Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0))
        @ Matrix.Translation((-center.x, -center.y, -center.z))
    )


def render_candidate(plan: dict, obj_plan: dict, asset_path: Path, output: Path, effective_yaw: float, args: argparse.Namespace) -> None:
    clear_scene()
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(asset_path))
    objects = imported_objects(before)
    for imported in objects:
        imported.name = f"{obj_plan['id']}_{imported.name}"
        if getattr(imported, "data", None):
            imported.data.name = f"{obj_plan['id']}_{imported.data.name}"
    transform_imported_asset(objects, candidate_plan_object(obj_plan, effective_yaw))
    setup_world()
    add_camera(plan, args.camera)
    setup_render(output, args.resolution_x, args.resolution_y)
    bpy.ops.render.render(write_still=True)


def main() -> None:
    args = parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    requested = [item.strip() for item in args.object_ids.split(",") if item.strip()]
    yaws = [float(item.strip()) for item in args.yaws.split(",") if item.strip()]
    objects = {str(obj.get("id")): obj for obj in plan.get("objects", []) if isinstance(obj, dict)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "tree_sage_pose_candidate_render_manifest_v1",
        "plan": str(args.plan),
        "asset_dir": str(args.asset_dir),
        "camera": args.camera,
        "resolution": [args.resolution_x, args.resolution_y],
        "yaws": yaws,
        "objects": {},
        "missing": [],
    }
    for object_id in requested:
        obj_plan = objects.get(object_id)
        asset_path = args.asset_dir / f"{object_id}.glb"
        if not obj_plan or not asset_path.exists():
            manifest["missing"].append(object_id)
            continue
        object_dir = args.output_dir / object_id
        object_dir.mkdir(parents=True, exist_ok=True)
        entries = {}
        for yaw in yaws:
            label = str(int(round(yaw)))
            output = object_dir / f"yaw_{label}.png"
            render_candidate(plan, obj_plan, asset_path, output, yaw, args)
            entries[label] = str(output)
        manifest["objects"][object_id] = {"renders": entries}
    (args.output_dir / "pose_candidate_render_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
